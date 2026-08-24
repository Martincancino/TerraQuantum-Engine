# INFORME 11 — DATOS, PERSISTENCIA Y RENDIMIENTO
## Formatos, interoperabilidad, reproducibilidad y coste

**Destinatario:** ingeniería de datos · sistemas · interoperabilidad geocientífica
**Rama auditada:** `fases-19-25-cierre` · commit `c810ed5`
**Base de evidencia:** lectura directa de `services/export_service.py`, `services/omf_export_service.py`, `exploration/storage.py`, `services/block_model_service.py`, `api/export_api.py`, `requirements.txt`, y una **traza completa de los dos caminos de exportación UBC-GIF** (§4).

> Autocontenido. Contiene un **problema de interoperabilidad verificado** (§4) que
> afecta al artefacto que un cliente cargaría en SimPEG o Leapfrog.

---

## 1. El inventario de formatos

TerraQuantum escribe y lee bastantes formatos. Conviene tenerlos en una sola tabla.

| Formato | Uso | Dónde |
|---|---|---|
| **CSV** | ingesta de campo y exportación tabular | `services/gravity_import_service.py`, `api/export_api.py` |
| **Parquet** | modelo de bloques persistido (esquema v4.0) | `services/block_model_service.py`, `exploration/storage.py` |
| **Arrow (LZ4)** | transporte backend→frontend del modelo | `services/block_model_service.py:1051` |
| **Zarr** | grillas 3D y Jacobiano *out-of-core* | `exploration/storage.py` |
| **JSON** | informes, entradas de corrida, manifiesto, estado | varios |
| **OMF v1** | interoperabilidad minera | `services/omf_export_service.py` (740 líneas) |
| **UBC-GIF** (`.msh` + `.den`/`.mod`) | inversión (GRAV3D, SimPEG) | `services/export_service.py:309` |
| **GSLIB** | geoestadística (SGeMS) | `services/export_service.py:644` |
| **VTR** | ParaView / Leapfrog | bundle ZIP |
| **ASEG-GDF2** | estándar geofísico australiano | `services/export_service.py` |
| **HTML** | informe imprimible | `reporting/report_generator.py` |

Las bibliotecas: `polars 1.40.0` para tablas, `pyarrow` (verificado 23.0.1), `zarr`
(verificado 3.2.1), `omf 1.0.1`, `scikit-image` para marching cubes
(`requirements.txt:10-12`, `42-43`, `88`, `105`).

---

## 2. La convención de ejes: el riesgo transversal

Todo este informe depende de un solo hecho. La convención interna es

$$
x = \text{ESTE},\qquad y = \text{PROFUNDIDAD (positiva hacia abajo)},\qquad z = \text{NORTE}
$$

confirmada por tres rutas independientes: ingesta
(`services/gravity_import_service.py:311`), exportación georreferenciada
(`services/omf_export_service.py:561`) y el módulo de sondajes
(`services/borehole_desurvey_service.py:16-17`).

Prácticamente **todos los formatos externos usan otra**. UBC-GIF usa (Este, Norte, Z hacia
**arriba**); OMF usa (u=Este, v=Norte, w=**arriba**). Es decir, cada exportación necesita
una permutación de ejes **y** una inversión del eje vertical.

Ese es el punto donde el sistema falla en un camino y acierta en otro.

---

## 3. La exportación OMF: bien hecha

`services/omf_export_service.py` trata la permutación como el problema central que es, con
una sección titulada «La permutación de ejes (el corazón de la fase)»
(`services/omf_export_service.py:297-299`).

```python
def permute_tq_grid_to_omf(values, spec):
    cube = np.asarray(values).reshape((spec.nx, spec.ny, spec.nz), order="F")  # (E, prof, N)
    ...
    return east_north_up.ravel(order="F")     # u rápido, luego v, luego w
```
(`services/omf_export_service.py:300-312`)

Y los tensores del elemento de volumen se construyen **ya permutados**
(`services/omf_export_service.py:383-385`):

```python
tensor_u = np.full(spec.nx, ...)   # Este   ← nx
tensor_v = np.full(spec.nz, ...)   # Norte  ← nz   (¡no ny!)
tensor_w = np.full(spec.ny, ...)   # arriba ← ny
```

Correcto: `v` (Norte) recibe `nz` y `w` (vertical) recibe `ny`.

### 3.1 Un matiz honesto sobre el lector

El módulo documenta que `omfvista` lee las celdas **transpuestas** respecto de la
especificación: hace `np.reshape(arr, (nu,nv,nw))` en orden **C** y luego
`.flatten(order="F")`, de modo que «un fichero **correcto** se ve transpuesto en ese lector»
(`services/omf_export_service.py:34-36`).

Es una distinción importante y bien hecha: el sistema declara que la discrepancia está en
el lector y no en el fichero, en lugar de "corregir" el fichero para que se vea bien en una
herramienta concreta —lo que lo rompería para todas las demás.

*(También se registra que `omf.OMFReader` no cierra el fichero, provocando errores 500 en
Windows.)*

### 3.2 La decisión de dependencia

Se fijó `omf==1.0.1` y se **descartó** el fork `mira-omf` 3.4.0 «pese a estar mejor
mantenido», porque arrastra `geoh5py` con licencia **LGPL** en un producto que se vende
(`requirements.txt:97-105`). Las dependencias transitivas se pinean a propósito porque «el
instalador firmado debe reconstruirse idéntico».

Es una decisión de licenciamiento y reproducibilidad tomada explícitamente. Correcta.

---

## 4. ⚠ PROBLEMA VERIFICADO — dos exportaciones UBC-GIF que no coinciden

Ésta es la sección principal del informe.

Existen **dos caminos** que escriben un fichero llamado `model.msh`, y **sólo uno permuta
los ejes**.

### 4.1 Camino A — exportación a disco (correcta)

`services/gravity_import_service.py:2120-2137`:

```python
# Permutación de ejes TerraQuantum → UBC-GIF:
# TQ: (x=Este, y=profundidad hacia abajo, z=Norte), Fortran (nx, ny, nz).
# UBC: (Este, Norte, Z hacia arriba). El exportador hace flip del último eje.
_arr3d  = _density_full.reshape((nx, ny, nz), order="F")   # (E, prof, N)
_arr_ubc = np.transpose(_arr3d, (0, 2, 1))[:, :, ::-1]     # (E, N, Z-up)

export_core_to_ubc(
    nx=nx, ny=nz, nz=ny,                    # UBC: nE, nN, nZ
    est_density=np.ascontiguousarray(_arr_ubc).ravel(order="F"),
    origin_z=-float(ny * block_size),       # techo del modelo = superficie (0 m)
)
```

Hace las **tres** cosas necesarias: transpone los datos, permuta los conteos al pasar los
argumentos (`ny=nz, nz=ny`), e invierte el eje vertical fijando el origen. Escribe
`model.msh` + `model.den`.

### 4.2 Camino B — bundle ZIP (sin permutar)

`services/export_service.py:769-780`:

```python
nx = max(int(inputs.get("nx") or 8), 1)
ny = max(int(inputs.get("ny") or 8), 1)
nz = max(int(inputs.get("nz") or 8), 1)
...
msh   = _ubc_msh_text(nx, ny, nz, bs)
dens  = _densities_from_parquet(run_dir, nx * ny * nz)
mod   = _ubc_mod_text(dens)
gslib = _gslib_text(dens, nx, ny, nz, bs)
```

y el generador escribe la cabecera literalmente
(`services/export_service.py:630-634`):

```python
return f"{nx} {ny} {nz}\n0.00 0.00 0.00\n{dx}\n{dy}\n{dz}\n"
```

Los valores `nx, ny, nz` vienen **directamente de las entradas de la corrida**, es decir en
convención TerraQuantum (Este, profundidad, Norte), y se escriben en las posiciones que
UBC-GIF reserva para (Este, **Norte**, **Z**). Sin transposición de los datos, sin
inversión del eje vertical, y con origen `0.00 0.00 0.00`.

### 4.3 La consecuencia, con números

Para un modelo de $n_x=20$, $n_y=10$ (profundidad), $n_z=20$ (Norte):

| Camino | Cabecera `.msh` | Interpretación UBC |
|---|---|---|
| A (disco) | `20 20 10` | 20 Este, 20 Norte, 10 en Z — **correcta** |
| B (ZIP) | `20 10 20` | 20 Este, **10 Norte**, **20 en Z** — permutada |

Y el problema no se limita a la cabecera:

- **`.mod`**: UBC-GIF espera el orden «z varía más rápido, luego y (N-S), luego x (E-W)»
  (`services/export_service.py:342-344`). El camino B escribe el array plano tal cual sale
  del Parquet, que está en orden Fortran de TerraQuantum (x rápido, luego profundidad,
  luego Norte). **El orden de recorrido tampoco coincide.**
- **`.gslib`**: `_gslib_text` escribe
  `Y_m = (iy+0.5)*bs` y `Z_m = −(iz+0.5)*bs`
  (`services/export_service.py:655-657`), es decir trata `iy` como Norte y `iz` como
  profundidad — exactamente al revés de la convención interna. Las coordenadas exportadas
  quedan intercambiadas.
- **Origen**: el camino B escribe `0.00 0.00 0.00`, mientras que UBC-GIF define el origen
  como la esquina **NO-superior** y el camino A calcula `origin_z = −ny·block_size`
  precisamente para que el techo del modelo quede en la superficie.

### 4.4 Por qué importa

El bundle ZIP es el **artefacto de entrega industrial**: el endpoint que lo produce se
documenta como «ZIP industrial con model.vtr, model.mod, model.msh, model.gslib,
manifest.json» (`api/export_api.py:6`), y el manifiesto lo declara legible por «UBC-GIF
Grav3D, SimPEG» (`services/export_service.py:728`).

La guía de usuario del propio proyecto instruye exactamente eso
(`docs/GUIA_DATOS_DE_CAMPO.md:180-182`):

```python
mesh  = discretize.TensorMesh.read_UBC("model.msh")
model = mesh.read_model_UBC("model.den")
```

Nótese la extensión: esa guía se refiere a `model.den`, que es el **camino A** (correcto).
El ZIP entrega `model.mod`. **Dos artefactos con el mismo nombre de malla y contenidos
distintos**, uno correcto y otro no.

Con una malla cúbica ($n_x=n_y=n_z$) el defecto es invisible. Con una malla realista
—típicamente más ancha que profunda— produce un modelo con ejes intercambiados que
`discretize` cargará sin protestar si los conteos son consistentes.

### 4.5 Estado

**Verificado por lectura de las dos rutas completas.** No se ejecutó ninguna exportación ni
se cargó el resultado en SimPEG. La comprobación es directa: generar el ZIP para un modelo
con $n_y \ne n_z$ y comparar la primera línea de `model.msh` con la del `model.msh` escrito
a disco por la misma corrida.

---

## 5. Persistencia de corridas y reproducibilidad

### 5.1 Qué se guarda

Por corrida (`services/project_store.py`, `services/block_model_store.py`):

- **entradas** (`inputs.json`) — la configuración con que se lanzó;
- **informe** (`report.json`) — métricas, diagnósticos, veredicto;
- **modelo** en Parquet (esquema v4.0);
- **estado** (`schedule.json`) para el seguimiento de progreso;
- **artefactos** de exportación (UBC, VTR, OMF…).

### 5.2 El manifiesto de auditoría

El bundle ZIP incluye un `manifest.json` con «versión TerraQuantum, Run ID, **Config Hash
SHA256**, parámetros de inversión y disclaimer NI 43-101 / JORC / SAMREC»
(`api/export_api.py:39-40`), y una lista de qué software puede leer cada fichero
(`services/export_service.py:728`).

Un hash SHA-256 de la configuración es la pieza correcta para trazabilidad: permite
afirmar que dos corridas usaron exactamente los mismos parámetros.

### 5.3 Lo que falta para reproducibilidad completa

| Elemento | ¿Se guarda? |
|---|---|
| Parámetros de inversión | **Sí** (`inputs.json` + hash) |
| Versión de TerraQuantum | **Sí** (manifiesto) |
| Semilla aleatoria | **Parcial** — fijas en código (`seed=0`, `seed=42`), no en el manifiesto |
| Versión de NumPy/SciPy | **NO DETERMINADO** — no se localizó en el manifiesto |
| Datos de entrada originales | **NO DETERMINADO** — no se localizó copia ni hash del CSV |
| Camino de solver realmente usado | **Sí** — se publica `solver_path_usado`, `bounded_usado`, `bounded_pedido` |
| Convergencia del solver | **Sí** — `istop`, `iters`, `solver_converged` |

Las dos primeras ausencias son relevantes porque `requirements.txt` fija versiones exactas
de NumPy y SciPy precisamente porque «controlan el resultado numérico del solver»
(`requirements.txt:8`). Si eso es cierto —y lo es—, la versión de esas bibliotecas debería
formar parte del registro de la corrida, no sólo del entorno de construcción.

La publicación del **camino de solver realmente usado** merece destacarse: se añadió tras
medir que el informe declaraba `bounded_solver_active: true` calculándolo desde la variable
de entorno solicitada, mientras el solver había despachado `LSQR+clip`
(`exploration/gravimetry.py:2536-2551`). Registrar lo que **pasó** en lugar de lo que se
**pidió** es la diferencia entre trazabilidad y ficción.

---

## 6. Transporte al frontend

El modelo viaja en **Arrow con compresión LZ4** (`services/block_model_service.py:1051`),
con niveles de detalle por octree y submuestreo (`services/block_model_service.py:962-1007`)
y modos de vista que limitan el volumen (`exploration`, `full`, `anomaly`, `doi_reliable`,
`profile`).

Decisiones correctas:

- **Arrow columnar** en lugar de JSON: para $10^5$ celdas con ~15 campos numéricos, JSON
  sería del orden de decenas de MB de texto que además hay que parsear; Arrow es binario y
  de coste de decodificación casi nulo.
- **`float32` en el transporte** aunque el cálculo sea `float64`: adecuado para
  visualización y la mitad de ancho de banda.
- **Umbral de advertencia de rendimiento a 200.000 vóxeles**
  (`services/block_model_service.py:15`).
- **LOD por octree**, de modo que el cliente no recibe más resolución de la que puede
  dibujar.

Un detalle de robustez del lado cliente que ya se documentó en otro informe pero pertenece
también aquí: `Number(null) === 0` en JavaScript hacía que un campo opcional emitido como
`null` por un `response_model` estricto se leyera como cero, poniendo «densidad=0 en TODA
la malla» (`terraquantum-web/lib/terraQuantumGeology.ts:257-263`). Es un fallo de
**frontera de serialización**, no de lógica: el tipo de defecto que sólo aparece cuando
dos sistemas de tipos se encuentran.

---

## 7. Rendimiento

### 7.1 Los costes dominantes

| Etapa | Complejidad | Nota |
|---|---|---|
| Construcción del kernel | $O(n\log n + \text{nnz})$ | KDTree + evaluación |
| Solve iterativo | $O(500\cdot\text{nnz}(A))$ | 2 matvecs por iteración |
| IRLS | × `compact_max_irls` | reensambla y resuelve |
| Selección de $\lambda$ | × 5 a × 20 | solves completos |
| Marching cubes | $O(n)$ por nivel | más Taubin |
| Serialización Arrow | $O(n)$ | con LZ4 |

### 7.2 Las salvaguardas

- **Memoria del kernel**: estimación por conteo de vecinos sin materializar listas, abortando
  al 60 % de la RAM libre con un error accionable (`exploration/gravimetry.py:57-100`).
- **Caché de geometría** de una entrada, validada por `np.array_equal`, con contador
  observable (`exploration/gravimetry.py:722-728`).
- **Cola de inversiones en procesos**, para que una corrida de 20+ minutos no reviente el
  proxy (`services/run_queue_service.py:1-9`).
- **Zarr para el Jacobiano** *out-of-core* — implementado y probado, **sin llamador en
  producción** (informe 07 §5.2).

### 7.3 El cuello de botella declarado

Las notas del proyecto registran el diagnóstico: una inversión conjunta de 96k vóxeles tarda
20+ minutos, y la ruta síncrona la cortaba. La cola lo resolvió. Queda registrada una
asimetría: la rama síncrona **no entra en el historial**, de modo que 12 levantamientos
lanzados por script dejaban la pantalla vacía. **NO DETERMINADO** si sigue vigente.

---

## 8. Resumen técnico

### Bien resuelto

- Permutación de ejes en OMF tratada como el problema central, con función dedicada y
  tensores construidos ya permutados.
- Distinción correcta entre «el fichero está mal» y «el lector lee transpuesto», sin
  corromper el fichero para agradar a una herramienta.
- Decisión de dependencia OMF tomada por licencia (LGPL) y reproducibilidad, con pines
  transitivos explícitos.
- Camino A de UBC-GIF: transposición, permutación de conteos e inversión del eje vertical,
  las tres cosas.
- Manifiesto con hash SHA-256 de configuración y disclaimer regulatorio.
- Publicación del camino de solver **realmente usado**, tras medir que antes se reportaba
  el solicitado.
- Arrow + LZ4 + LOD para el transporte, con `float32` y umbral de advertencia.
- Cola en procesos con cancelación real.

### Problemas detectados

1. **El bundle ZIP escribe UBC-GIF sin permutar los ejes** (§4): cabecera `.msh`, orden del
   `.mod` y coordenadas del `.gslib`, más origen `0 0 0` sin inversión vertical.
   **Verificado por lectura de ambas rutas.**
2. **Dos artefactos `model.msh` con contenidos distintos**, uno correcto (disco, junto a
   `.den`) y otro no (ZIP, junto a `.mod`).
3. **La reproducibilidad no incluye la versión de NumPy/SciPy** pese a que el propio
   `requirements.txt` declara que controlan el resultado numérico.
4. **No se localizó copia ni hash del dato de entrada original** en el registro de corrida
   (**NO DETERMINADO**).
5. **Capacidad *out-of-core* sin llamador en producción.**

---

## 9. Preguntas abiertas para revisión académica

---

### Pregunta 1 — Dos exportaciones del mismo formato que no coinciden (prioritaria)

**Pregunta.** El sistema escribe UBC-GIF por dos caminos. El de disco transpone los datos,
permuta los conteos e invierte el eje vertical; el del bundle ZIP escribe `nx ny nz` tal
cual, con origen `0 0 0` y sin transponer. Para un modelo $20\times10\times20$ las cabeceras
resultan `20 20 10` y `20 10 20`. ¿Confirma que el segundo es incorrecto respecto de la
especificación UBC-GIF? ¿Y qué comprobación automática recomendaría para que dos escritores
del mismo formato no puedan divergir — por ejemplo, un único escritor canónico, o un test
de ida y vuelta que reimporte el fichero y compare contra el modelo original?

**Evidencia.** `services/gravity_import_service.py:2120-2137` (camino correcto);
`services/export_service.py:769-780` y `630-634` (camino sin permutar);
`services/export_service.py:342-344` (el orden que UBC exige para el `.mod`);
`services/export_service.py:655-657` (coordenadas del GSLIB);
`api/export_api.py:6` y `services/export_service.py:728` (el ZIP como entrega industrial).

**Qué sabemos.** Que con malla cúbica el defecto es invisible, y que el proyecto **ya tiene**
un test de ida y vuelta para OMF, de modo que el patrón existe y podría extenderse.

**Qué NO sabemos.** Si `discretize.TensorMesh.read_UBC` fallaría ruidosamente o cargaría en
silencio un modelo con ejes intercambiados. **No se ejecutó.**

---

### Pregunta 2 — Qué debe guardarse para que una corrida sea reproducible

**Pregunta.** Se guardan parámetros, hash SHA-256 de configuración, versión de
TerraQuantum, camino de solver realmente usado e `istop`. **No** se guardan las versiones de
NumPy/SciPy —pese a que `requirements.txt` declara que «controlan el resultado numérico del
solver»— ni, hasta donde pudimos ver, un hash del CSV de entrada. ¿Qué conjunto mínimo
consideraría suficiente para que un tercero pueda reproducir bit a bit un resultado
publicado en un informe técnico?

**Evidencia.** `api/export_api.py:39-40` (el manifiesto); `requirements.txt:8` (la
declaración sobre NumPy/SciPy); `exploration/gravimetry.py:2536-2551` (la publicación del
camino real).

---

### Pregunta 3 — Corregir el fichero o corregir el lector

**Pregunta.** El sistema documenta que `omfvista` lee las celdas transpuestas respecto de la
especificación, de modo que **un fichero correcto se ve mal** en esa herramienta. El
proyecto decidió mantener el fichero correcto. ¿Es la decisión adecuada, o en un producto
comercial pesa más que el cliente vea bien su modelo en la herramienta que efectivamente
usa? ¿Y cómo se comunica algo así al usuario sin sembrar dudas sobre el fichero?

**Evidencia.** `services/omf_export_service.py:34-36`.

---

### Pregunta 4 — La frontera de serialización como fuente de errores

**Pregunta.** Un campo opcional emitido como `null` se leía como `0` en el cliente
(`Number(null) === 0`), poniendo densidad cero en toda la malla. Es un fallo de la frontera
entre dos sistemas de tipos, no de la lógica de ninguno. Dado que el proyecto ya **genera**
los tipos TypeScript desde el esquema Pydantic, ¿qué mecanismo adicional recomendaría —tipos
generados que distingan `null` de ausente, validación en tiempo de ejecución en el cliente,
o prohibir campos opcionales numéricos en el contrato?

**Evidencia.** `terraquantum-web/lib/terraQuantumGeology.ts:257-263`;
`scripts/ci/generate_frontend_types.py`.

---

### Pregunta 5 — Precisión en el transporte

**Pregunta.** El cálculo es `float64` y el transporte al visor `float32`. Para densidades en
t/m³ con contrastes del orden de 0,01–1,0, `float32` da ~7 dígitos significativos, de sobra.
¿Ve algún caso en esta cadena donde la pérdida importe — por ejemplo, coordenadas UTM
absolutas, donde un easting de 7 dígitos más decimales ya roza el límite de `float32`?

**Evidencia.** `services/block_model_service.py:1051` (Arrow);
`terraquantum-web/lib/terraquantum/frontendApi.ts:2083-2085` (`getF32`).

**Nota.** Las coordenadas del modelo son **locales** (relativas al origen del levantamiento),
no UTM absolutas, lo que mitiga el riesgo. Pero el enriquecimiento sí añade `lat`/`lon` por
celda.

---

### Pregunta 6 — Capacidad *out-of-core* no cableada

**Pregunta.** Existe un camino que construye el Jacobiano por lotes y lo transmite a Zarr
para no tenerlo en RAM, con tests, pero sin llamador en producción; y por otro lado hay una
salvaguarda que **aborta** la corrida si el kernel no cabe en el 60 % de la RAM. ¿No sería
preferible que la salvaguarda **derive** al camino *out-of-core* en lugar de abortar?
¿O hay razones para preferir fallar rápido y pedir al usuario que reduzca la malla?

**Evidencia.** `exploration/gravimetry.py:3815` (out-of-core);
`exploration/gravimetry.py:88-100` (la salvaguarda que aborta).

---

### Pregunta 7 — Formatos que nadie pidió

**Pregunta.** El bundle incluye VTR, GSLIB, ASEG-GDF2, UBC-GIF y OMF. Mantener cinco
formatos de salida tiene coste, y al menos dos de ellos (§4) tienen la permutación de ejes
sin verificar. Desde la práctica geocientífica: ¿cuáles son realmente indispensables para un
consultor geofísico, y cuáles se pueden retirar sin perder interoperabilidad efectiva?

**Por qué surge.** Es mejor mantener dos formatos correctos que cinco de los cuales dos
están mal.

---

*Fin del informe 11. El informe 07 trata el rendimiento del cómputo; el 09, las
transformaciones geométricas que estos formatos deben deshacer; el 08, la arquitectura que
los produce.*
