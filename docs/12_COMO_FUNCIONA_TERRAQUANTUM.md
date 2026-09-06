# TerraQuantum — Cómo funciona por dentro

> **Documento de referencia técnica completa** · escrito el 2026-09-03 leyendo el código
> de la rama `fases-19-25-cierre` (HEAD `d6701e1`). Cubre la matemática, la física, la
> arquitectura numérica y el sistema de verificación.
>
> **Regla de este documento:** la fuente de verdad es el código ejecutable, no los nombres
> de las funciones ni los comentarios ni la documentación previa. Cada afirmación técnica
> lleva `archivo:línea`. Donde el código y la documentación discrepan, gana el código y se
> anota la discrepancia.

---

## 0. Cómo leer esto

Tres niveles de afirmación, separados a propósito en todo el texto (la convención viene de
`docs/academic/00_INDICE.md`):

| Nivel | Pregunta | Ejemplo |
|---|---|---|
| **(a) Lo que el código hace** | ¿Qué aritmética ocurre? | se minimiza `‖W_d(Gm−d)‖² + λ_eff²‖m̃‖² + λ_sp²‖L·W_s·m̃‖²` |
| **(b) Lo que significa** | ¿Qué propiedad matemática tiene? | es Tikhonov con seminorma de curvatura; los campos constantes están en el núcleo de `L` |
| **(c) Lo que se puede decir del mundo** | ¿Qué se afirma de la roca? | existe una distribución de contraste de densidad compatible con el dato. **No** que sea la real |

El sistema colapsa (a) en (c) si nadie lo impide. Buena parte de la maquinaria que se
describe en §7, §8 y §11 existe justamente para impedirlo.

**Cifras del repositorio** (medidas con `git ls-files` + `wc -l`):

| | |
|---|---|
| Ficheros versionados | 996 (490 `.py`, 177 `.ts/.tsx`) |
| Backend, código de producción | ~55.400 LOC (`services` 30.995 · `exploration` 11.754 · `api` 6.862 · `schemas` 3.035 · `reporting` 1.848 · `core` 1.881 · `middleware` 53) |
| Backend, tests | 54.120 LOC · **2.218 funciones `test_*`** en 232 ficheros |
| Frontend | 34.411 LOC TypeScript/TSX |
| Endpoints HTTP | 60 |
| Dependencias Python | 105 paquetes en el cierre resuelto (`requirements.lock`), intérprete **3.14.4** |
| Commits | 303 |

---

## 1. Mapa del sistema

TerraQuantum es un sistema de **inversión de campos potenciales** (gravimetría y
magnetometría) para exploración minera, local-first: el dato del cliente nunca sale de su
máquina.

```
CSV crudo de campo
   │
   ├─ [analyze-columns]  sniffer + plan de mapeo por ROL (nunca adivina: pregunta)
   ├─ [parse-rows]       parseo en Python (no en JS): unidades, decimal-coma, junk
   ├─ [enrich-package]   correcciones de gabinete: marea, deriva, GRS80, FAC, Bouguer, TC,
   │                     coordenadas (pyproj/Helmert), elevación (DEM), IGRF-14
   ├─ [load-package]     ENCOLA la inversión (proceso aparte, cancelable)
   │
   ▼
MOTOR (exploration/)                    ORQUESTADOR (services/geophysics_service.py)
   malla tensor + padding               → validación cruzada de entrada
   kernel forward disperso (CSR)        → selección de λ (Morozov / punto de operación)
   sistema aumentado Tikhonov           → PGI, sondajes, litología, geología implícita
   LSQR / LSMR / TRF / FISTA            → DOI, σ posterior, null-space, targeting
   IRLS minimum-support                 → diagnósticos R01–R06, perfil de resolución
   │                                    → veredicto reconciliado (worst-of)
   ▼
block_model.parquet + report.json + artefactos (VTK, UBC-GIF, OMF, GSLIB, ASEG-GDF2, CSV)
   │
   ▼
FRONTEND (Next.js 16 / React 19 / three.js) — visualiza. NO calcula física.
```

**Separación dura** (`.claude/CLAUDE.md`, con gate de CI que la vigila): toda la física,
matemática e inversión ocurre en el backend. El frontend consume APIs y pinta. No se
duplica lógica de Python en TypeScript.

### 1.1 Las cuatro capas del backend

| Capa | Directorio | Responsabilidad | ¿Contiene dominio geofísico? |
|---|---|---|---|
| **Motor** | `exploration/` | álgebra lineal + física de campos potenciales | **Sí**, es su trabajo |
| **Servicios** | `services/` | orquestación, ingesta, correcciones, exportación, persistencia | Sí |
| **API** | `api/` | contratos HTTP, validación, encolado | No (capa delgada) |
| **Core** | `core/` | configuración, errores, logging, licencia, métricas | **0 %**, se vació a propósito |

El 0 % de dominio en `core/` es una decisión medida: en la Fase 6 se movieron
`block_model_store`, `geo_utils` y `gee_client` a `services/`, y se borró
`MAGNETIC_SUSCEPTIBILITY_PRESETS` de `core/config.py` — una tabla petrofísica por litología
con cero consumidores de producción, cuyo único lector era un test que la comprobaba contra
sí misma (`core/config.py:196-213`).

---

## 2. Convenciones que hay que saber antes de leer una fórmula

### 2.1 Ejes

`docs/11_CONVENCION_DE_EJES.md`, decidido por la Fase 18 tras medir que dos módulos
documentaban convenciones **opuestas** y nada las comparaba:

| slot | significado | signo |
|---|---|---|
| `x_m` / eje 0 | **Este** (easting) | + hacia el Este |
| `y_m` / eje 1 | **Profundidad** | **+ hacia ABAJO** |
| `z_m` / eje 2 | **Norte** (northing) | + hacia el Norte |

Es un marco **levógiro** respecto del ENU habitual, porque `y` apunta hacia abajo. Se
mantuvo así porque cambiarlo movería gravimetría, sondajes, topografía y exportadores; lo
que se corrigió fue el motor magnético, que creía `x=Norte, z=Este`.

Consecuencia directa, `exploration/magnetometry.py:87-106`:

```
f̂ = (cos I · sin D,   sin I,   cos I · cos D)
```

y **no** `(cos I·cos D, sin I, cos I·sin D)`, que sería correcta sólo si el eje 0 fuese el
Norte. El defecto que esto cerró (**ACAD-1**) equivalía a `D_ef = 90° − D`: en Chile, **86°
de desvío** y Pearson `r = −0,05` contra la anomalía real. Con `D = 45°` el defecto es
invisible, y por eso sobrevivió tanto.

Para Chile (hemisferio sur) `I ≈ −30°`, así que la componente `y` (hacia abajo) del campo
sale negativa: el campo apunta hacia arriba, como debe ser. La norma de `f̂` es exactamente 1.

### 2.2 Orden de memoria

**Fortran (`order='F'`) en todo el backend.** Índice plano:

```
idx = ix + nx·iy + nx·ny·iz
```

Declarado en `exploration/gravimetry.py:1260-1266` y respetado por el Laplaciano
(`_build_laplacian`), los operadores de gradiente (`exploration/geophysics_math.py`), el
block model y los exportadores. Un `ravel()` en orden C en cualquiera de esos sitios rompe
la correspondencia celda↔columna sin fallar ruidosamente.

### 2.3 Unidades

| Magnitud | Unidad interna | Notas |
|---|---|---|
| Gravedad observada | **m/s²** | el CSV puede traer mGal/µGal/Gal; convierte `convert_to_ms2` (`services/gravity_import_service.py:454`). 1 mGal = 1e-5 m/s² |
| Correcciones de gabinete | **mGal** | `services/gravity_corrections_service.py` trabaja íntegro en mGal; la conversión ocurre en el empalme |
| Densidad | **t/m³** | numéricamente igual a g/cm³. El kernel multiplica por 1000 para pasar a kg/m³ (`gravimetry.py:770`) |
| Susceptibilidad | **SI adimensional** | referencia base κ=0 (roca huésped no magnética) |
| Campo magnético | **nT** | µ₀ se cancela en el prefactor |
| Coordenadas | **m** | locales; la georreferenciación vive aparte |

Las dos regresiones de escala más peligrosas del proyecto ocurrieron por aquí: el bug de
`mGal × 1e-5` en DO-27 y la **doble corrección de Bouguer** (commit `9045719`). Ninguna de
las dos habría puesto roja la CI de entonces — por eso existe
`tests/test_fase3_calibracion_absoluta.py` (§11.3).

---

## 3. El dato: de un CSV de campo a observaciones invertibles

El activo de robustez del producto no es el solver: es que un CSV real (con comas
decimales, cabeceras IGRF embebidas, unidades en pies, filas de metadata y nombres de
columna en español) entre sin corromperse en silencio.

### 3.1 Sniffing y parseo

`services/csv_sniffer_service.py` + `services/gravity_import_service.py:722-918`.

- **Delimitador**: se detecta sobre líneas no vacías; si es ambiguo se lanza
  `AmbiguousDelimiterError` en lugar de elegir.
- **Decimal-coma**: `_detect_semicolon_decimal_comma` (`:737`) discrimina el caso europeo
  `;` + `,` decimal. Fue un bug de corrupción silenciosa real (commit `e7d2858`): un
  `1,234` leído como `1234` cambia la anomalía tres órdenes de magnitud sin dar error.
- **Filas de metadata**: `_is_metadata_row` (`:466`) marca como metadata cualquier fila
  donde una columna de coordenada trae texto no numérico. Distingue cabeceras e IGRF
  embebidos de datos reales. Una coordenada **vacía** no es metadata: se deja a la
  validación por fila, que la rechaza con un mensaje claro.
- **Unidades**: `canonicalize_unit` (`:71`) normaliza `mgal/milligal/miligal → mGal`,
  `ugal/µGal/microgal → µGal`, `m/s2 / ms2 / m/s^2 / ms-2 → m/s2`, `gamma → nT`. La
  normalización quita espacios, superíndices, `^`, `·` y unifica `µ/μ → u`.

**Deuda declarada, no cerrada** (`gravity_import_service.py:530-537`): el pipeline
magnético **canonicaliza** la unidad pero **no rechaza** una desconocida. Cerrarlo cambia
qué CSVs se aceptan, o sea comportamiento de ingesta, no limpieza.

### 3.2 Mapeo de columnas por rol

`services/column_mapping_service.py` + `services/csv_analysis_service.py`.

El principio, que cerró **H-F11-1**: el sistema **no adivina el rol de una columna, lo
pregunta**. El alias `X,Y,Z` mandaba el northing a PROFUNDIDAD; borrar el alias no bastaba,
porque el siguiente CSV traería otra ambigüedad. La solución es un plan de mapeo donde cada
columna se asigna a un **rol** (`x`, `z`, `elevation`, `g_obs`, `sigma`, `magnetic_nt`,
`time_utc`, `station_id`, `lithology`…), la sugerencia se **propone** en el rol y el usuario
la acepta a mano.

`choose_gravity_column` (`:493`) y `choose_magnetic_column` (`:540`) mantienen una
**prioridad exacta** y sólo después un fallback fuzzy normalizado, nunca al revés, para que
añadir sinónimos no reordene lo que ya funcionaba.

### 3.3 Coordenadas

Dos caminos, ambos reales:

1. **Reproyección CRS** — `services/coordinate_transform_service.py` con `pyproj` (el
   `proj.db` viaja bundleado en el instalador). Lat/lon → UTM de la zona correspondiente.
2. **Helmert 2D** — `services/helmert_transform_service.py`, para cuando el survey está en
   un sistema local arbitrario y hay ≥2 puntos de control con coordenadas reales:

   ```
   E = a·x − b·z + tE
   N = b·x + a·z + tN        con  a = s·cosθ,  b = s·sinθ
   ```

   4 incógnitas. Con 2 puntos es exacto; con ≥3 se resuelve por mínimos cuadrados y **el
   residual valida el anclaje**: por encima de `DEFAULT_RESIDUAL_WARN_M = 10.0` m se marca
   `confidence` LOW. Un solo punto fija la posición pero **no la rotación ni la escala**, y
   el servicio lo rechaza explícitamente con ese argumento (`:44-50`).

### 3.4 Las correcciones de gabinete (la física del dato)

`services/gravity_corrections_service.py`. Constantes CODATA 2018 / GRS80 (`:28-37`).

Cadena completa:

```
g_leída → −marea → −deriva → −γ(φ) → +FAC → −BC → +TC = anomalía de Bouguer completa
```

**Orden**: marea primero (astronomía pura), deriva después, porque los cierres de base se
evalúan sobre lecturas ya libres de marea (`apply_field_prereductions:237`).

#### Marea terrestre — Longman (1959)

`services/earth_tide_service.py`. Se resta la aceleración de marea calculada a partir de
(lat, lon, elevación, instante UTC). Exige la columna de tiempo: si falta, o si **algún**
timestamp no parsea, se lanza `ValueError`. No se corrige a medias, porque una corrección
parcial corrompería en silencio (`:275-284`).

#### Deriva instrumental

`services/drift_correction_service.py`. Necesita la estación **base** cuyas re-ocupaciones
cierran el loop. Si no se declara, el servicio **pregunta** (patrón `needs_context`) y
propone la candidata: el `station_id` que más se repite (`suggest_base_station`). Si ningún
id se repite, lo dice: «sin re-ocupaciones no hay cierres que midan la deriva». Los tiempos
se ordenan, se corrige, y se restaura el orden original con una permutación inversa.

#### Gravedad normal — GRS80 / Somigliana

`compute_normal_gravity_grs80:42`:

```
γ(φ) = γ_e · (1 + k·sin²φ) / √(1 − e²·sin²φ)

γ_e = 9,7803267715 m/s²     k = 0,001931851353     e² = 0,0066943800229
```

#### Corrección de aire libre (FAC), dependiente de latitud

`compute_free_air_correction:64` — Heiskanen & Moritz (1967), fórmula 3-57:

```
FAC = (0,3087691 − 0,0004398·sin²φ)·h  −  7,2125e-8·h²      [mGal]
```

Positiva para `h > 0`, se **suma**. La variante de coeficiente fijo 0,3086 se **eliminó** en
la Fase 6 (`:82-86`): cero llamadores, y mantener las dos era ofrecer una elección cuya
única diferencia posible es un resultado peor.

#### Corrección de Bouguer de placa infinita

`compute_bouguer_correction:94`:

```
BC = 0,04193 · ρ_red · h        [mGal],  con ρ_red en g/cm³
```

El coeficiente 0,04193 corresponde a `2πG` con `G = 6,6743e-11` (Hinze et al. 2005,
estandarización NAGD). Se **resta**.

#### Corrección de terreno — la que corrigió ACAD-0

`compute_terrain_correction_column:116`. Cada celda del DEM es una **columna vertical** de
sección `dem_cell_size²` entre la cota de la estación y la del terreno; se suma la
**componente vertical** de su atracción, que es lo que mide un gravímetro. Integrando
`z/(r²+z²)^{3/2}` entre 0 y Δh:

```
TC = Σ G·ρ·A·(1/r − 1/√(r²+Δh²))                    [forma cerrada]
   = Σ G·ρ·A·Δh² / (r·s·(r+s)),   s = √(r²+Δh²)     [forma estable — LA IMPLEMENTADA]
   ≈ Σ G·ρ·A·Δh²/(2r³)                               [límite de campo lejano]
```

Se implementa la segunda porque la primera pierde dígitos por cancelación cuando `Δh ≪ r`
(medido: 8·10⁻⁶ de error relativo a r = 22 km con Δh = 0,1 m) y porque el límite de campo
lejano diverge en terreno escarpado cercano (medido: **202×** el prisma de Nagy para
Δh = 1000 m a r = 50 m, frente a 0,96× de la forma cerrada).

**Qué arregló esto (Fase 17, defecto ACAD-0).** Hasta 2026-08-25 la función sumaba
`G·ρ·A·|Δh|/r²`, el **módulo** de la atracción de una masa puntual, sin proyectar sobre la
vertical. Le faltaba el factor `Δh/(2r)`, de modo que sobrestimaba por `2r/|Δh|`, un factor
que **crece con la distancia**, con radio de integración por defecto de 22 km. Medido: 200×
para una celda a 1 km con 10 m de desnivel, 66× a 1 km con 30 m, y **14,8×** en el total de
un cono de 500 m, sobre una señal de exploración de 0,1–10 mGal. La fórmula que proponía el
**plan** de la fase también era mala; la que quedó salió de re-derivarla.

**Aproximaciones que siguen vivas (son el modelo, no bugs):**

- La sección de la celda se colapsa a un punto en el horizontal. El error contra el prisma
  exacto de Nagy decae como ≈ `0,375·(celda/r)²`: medido 9,4·10⁻⁴ a r = 20 celdas y
  7,9·10⁻² a r = 2 celdas. Siempre **subestima** (0,71–0,99 del prisma), nunca diverge.
- La celda que contiene la estación (r = 0) queda excluida por la máscara.
- Residuo declarado del 48 %: falta Nagy en campo cercano (registro de la Fase 17).

`TC ≥ 0` es **estructural**, no un recorte: el numerador es `Δh²` y el denominador es
positivo para todo `r > 0`. Se quitó el `np.maximum(tc, 0.0)` a propósito, porque un guard
inerte aparenta defender algo que la fórmula ya garantiza. Físicamente: colina y valle del
mismo desnivel aportan lo mismo, y ambos **reducen** la gravedad medida.

Los alias `compute_terrain_correction_pointmass` y `_prism` se conservan por
compatibilidad, pero los dos nombres mentían sobre la fórmula y está anotado.

#### Idempotencia: no corregir dos veces

`apply_all_corrections:351` lee `gravity_type_in` y **salta** lo ya aplicado:
`free_air_anomaly` ya trae latitud+FAC, `bouguer_anomaly` además BC,
`complete_bouguer_anomaly` además TC. Este bloque es el que evita repetir el bug de la doble
corrección de Bouguer. Además rechaza `tc_values_mgal` con valores negativos
(«matemáticamente imposible») y exige elevaciones si se pide FAC/BC/TC.

#### Test de Nettleton

`nettleton_analysis:471` — barre densidades de reducción y elige la que **minimiza
|r(BA, elevación)|**. Es el método clásico para estimar la densidad de la roca superficial.

### 3.5 Magnetometría: IGRF-14 offline

`services/igrf_service.py`. Síntesis de armónicos esféricos de Gauss con los coeficientes
públicos IAGA bundleados (`services/data/igrf14coeffs.txt`), port fiel de `igrf13syn`
(BGS/NOAA). Devuelve `I`, `D`, `F` en (lat, lon, altitud, fecha):

```
H = √(X²+Y²)        F = √(X²+Y²+Z²)
D = atan2(Y, X)     I = atan2(Z, H)
```

con X = norte, Y = este, Z = vertical hacia abajo, radio de referencia 6371,2 km. Validez
1900,0 ≤ fecha ≤ 2030,0 (modelo principal a 2025,0 + variación secular 2025–2030); fuera de
rango → `IgrfOutOfRangeError`. Sin red: es un requisito local-first, y el fichero de
coeficientes es una de las cosas cuya ausencia **aborta el build** (§11.8).

---

## 4. La malla

### 4.1 Malla tensorial con padding geométrico

`services/inversion_kernel_service.py:57` (`build_padded_tensor_grid`).

Un bloque **core** uniforme `nx × ny × nz` de celdas `dx`, más `n_pad = 5` capas de padding
en cada una de las 6 caras, con crecimiento geométrico `h_{i+1} = h_i · 1,3`.

**Por qué el padding es física y no un truco numérico:** la Tierra no termina en el borde
del survey. Sin padding, una fuente en el límite no tiene dónde ubicarse y satura las celdas
del core (artefacto de borde, medido en Raglan). Las celdas de padding dan vecinos al
Laplaciano (condición de frontera suave `m → fondo`) y absorben el campo lejano. El solver
las penaliza aparte con `padding_kappa`.

Los centros del core se alinean **exactamente** con los de `build_voxel_grid`:
`x_core_k = (k + 0,5)·dx`. Eso es lo que permite descartar el padding al final
(`est_density[is_core]`) sin remapear nada.

El joint usa una variante, `_build_joint_padded_grid`
(`services/joint_inversion.py:190`), que **no** padea la cara `−Y`: en campos potenciales no
hay tierra sobre el survey, y esas celdas las enmascararía el solver como aire, rompiendo la
co-localización malla-completa que exigen los operadores de gradiente y el kernel forward
compartidos. Padding lateral (±X, ±Z) y hacia abajo (+Y) es la condición de frontera física
correcta.

### 4.2 Celdas activas y topografía

`exploration/potential_field_core.py:156` (`active_cells_from_topography`):

```
techo_del_vóxel = y_c − dy/2
activa  ⟺  techo_del_vóxel ≥ profundidad_del_terreno
```

`topography_elevations=None` equivale a **terreno plano a cota 0**. Ese fallback existía
silencioso (H-27) y ahora se declara: si la interpolación de superficie falla y la corrida
sigue plana, `topography_run_warnings` (`geophysics_service.py:330`) emite un aviso que
viaja al frontend. El caso «el survey no trae elevaciones» **no** genera aviso: es una
entrada declarada por el usuario, no una degradación inesperada del motor.

Ese aviso llegó tarde a la conjunta: hasta la Fase 23, `run_joint_inversion` pasaba
`topography_elevations=None` **fijo**, y la misma corrida con y sin `sensor_elevations_masl`
devolvía el modelo **idéntico bit a bit**, con el **15,93 %** del contraste recuperado
dentro de celdas que son **aire**.

### 4.3 Cut-cell

Con `cut_cell_topography=True`, la celda cortada por el terreno no es binaria
activa/inactiva: lleva una **fracción de volumen** (`cell_fraction`, en
`_lsqr_mascara_activa`) con piso `cutcell_min_fraction`. Reduce el escalonado de la
superficie.

### 4.4 Octree / TreeMesh

`services/octree_mesh_builder.py` + `exploration/treemesh.py`.
`should_auto_use_treemesh` se activa cuando el survey supera **50 km** de extensión **o** la
grilla regular excede **50k celdas**. `use_treemesh` en el esquema puede forzar cualquiera de
los dos caminos.

Detalle numérico que costó un OOM: el kernel de diagnóstico Core (`kernel_sparse`) se
construye **sólo** en el camino regular. Antes se armaba incondicionalmente y el camino
TreeMesh lo descartaba — con un cutoff denso, ~1,7 GB tirados a la basura y doble build en
DO-27 (`geophysics_service.py:3400-3406`).

En el Octree el kernel se construye desde la malla adaptativa con **celdas de tamaño
variable**: `_build_sparse_kernel_variable` (`gravimetry.py:946`) usa el tamaño y el volumen
**por celda** en lugar del escalar uniforme. Esa ruta es aditiva y opt-in: con
`cell_d* = None` el comportamiento es byte-idéntico a la uniforme, incluida la caché.

### 4.5 Dominio observable (poda R-05)

`observable_domain_mask` (`potential_field_core.py:180`): columnas de `G` con sensibilidad
no nula a **algún** sensor.

```
col_sens_j = Σ_i G_ij²          activa ⟺ col_sens_j > 1e-6 · max_j(col_sens_j)
```

Las columnas nulas (celdas más allá del cutoff para todos los sensores) sólo añaden plateau
de mínima norma y **saturación espuria en el bound**. Las celdas podadas reciben contraste 0
→ `base_density`, no `density_min` (`gravimetry.py:2909-2914`), y ese detalle se corrige
también en el conteo de saturación R-03 para no inflarlo.

---

## 5. El problema directo (forward)

### 5.1 Gravimetría

`exploration/gravimetry.py:704` (`GravimetryForward`).

**Kernel híbrido por distancia**, con `a_eq = √(dx²+dy²+dz²)` y
`threshold = min(4·a_eq, cutoff_radius)`:

- **Campo cercano** (`r ≤ threshold`): **prisma rectangular exacto de Nagy (1966)**,
  componente vertical `g_y`.
- **Campo lejano** (`threshold < r ≤ cutoff_radius`): **masa puntual** vectorizada,
  `G·V·1000·Δy / r³`.
- Más allá del `cutoff_radius`: contribución 0, no se almacena.

#### Nagy — `_nagy_prism_safe:733`

Suma con signo sobre las 8 esquinas del prisma, `signo = (−1)^{i+j+k}`, con
`(x,y,z) = (esquina − sensor)` y `r = √(x²+y²+z²)`:

```
g_y/ρ = G·1000 · Σ_esquinas signo · [ x·ln(z+r) + z·ln(x+r) − y·atan2(x·z, y·r) ]
```

**Anti-singularidad** — cinco decisiones, todas deliberadas:

- `eps = 1e-10 · min(dx,dy,dz)`: escala con el vóxel, no es un epsilon fijo.
- `r = √(x²+y²+z²+eps)`: el eps va **dentro** del radicando, lo que evita `r=0` cuando el
  sensor coincide con el centroide.
- `atan2(x·z, y·r + eps)` obligatorio: evita la división por cero de `arctan(xz/yr)` en
  `y = 0`.
- `log(max(arg, eps))` en vez de `log(|arg| + eps)`.
- `float64` obligatorio.

`np.minimum` (no `min()`) soporta tanto `dx/dy/dz` escalares (ruta uniforme, resultado
idéntico) como arrays por celda (ruta TreeMesh). El `1000.0` es la conversión t/m³ → kg/m³.

#### Estructura numérica del ensamblado

`_build_sparse_kernel:773`. Es HPC real, no un doble bucle:

1. KDTree (`scipy.spatial.cKDTree`) sobre los centros de las celdas **activas** únicamente.
2. **Dos** consultas masivas para TODOS los sensores (`query_ball_point` con `threshold` y
   con `cutoff_radius`), en lugar de `2·n_obs` llamadas.
3. `ThreadPoolExecutor` con `cpu_count()−1` workers; cada worker devuelve sus tripletas
   `(rows, cols, data)` sin escrituras compartidas (el `staticmethod` de Nagy es
   thread-safe y no contiende por el GIL en el cálculo vectorizado).
4. Los futures se recogen **en orden de índice** → tripletas deterministas → matriz
   bit-idéntica entre corridas. Esto no es cosmético: es lo que hace posible el gate de
   byte-identidad (§11.5).
5. `sp.csr_matrix((data,(rows,cols)), shape=(n_obs, n_active))`.

**Caché de una geometría** (`:730`, `:806-820`): el kernel depende SÓLO de la geometría
(coordenadas activas, sensores, `dx/dy/dz`, cutoff), **no** de λ, `m_ref` ni ruido. Dentro
de una corrida, el solve, el barrido de Morozov, el DOI y la UQ reusan la misma geometría.
La validación es por `np.array_equal` (sin riesgo de colisión de hash) y el uso es
read-only. `kernel_build_count` expone cuántas construcciones reales hubo, y lo miden los
tests (`tests/test_kernel_cache.py`).

**Guard de memoria** (`_guard_sparse_kernel_memory:57`): antes de materializar nada se
estima el NNZ con `query_ball_point(return_length=True)`, que devuelve **sólo el conteo**
(O(n_obs) de memoria, sin materializar las listas de índices, que son justamente lo que
dispara el OOM), y se compara con `psutil.virtual_memory().available`. A 24 bytes por
no-cero y con margen del 60 %, si no cabe se lanza
`SolverMemoryError("SOLVER_KERNEL_TOO_DENSE")` con `fill_pct`, `cutoff_m`, `n_active`,
`n_obs`. **No es un tope de vóxeles**: depende de la dispersión real. Un kernel disperso de
millones de celdas pasa; uno denso de pocas se detiene. Si SciPy es antiguo y no soporta
`return_length`, degrada seguro: no estima, no rompe.

### 5.2 Magnetometría

`exploration/magnetometry.py:125` (`MagnetometryForward`). El modelo invertido es la
**susceptibilidad κ (SI)**, con referencia base κ=0, de modo que el «contraste» coincide con
κ.

Prefactores (µ₀ ya cancelado):

```
C = B₀·V / 4π    [nT·m³]     — dipolo
D = B₀ / 4π      [nT]        — prisma (el volumen queda DENTRO de la integral del tensor)
```

#### Régimen dipolar (por defecto)

```
G_ij = C · (3·(f̂·r_vec)² − r²) / r⁵ ,      r_vec = celda − sensor
```

#### Régimen de prisma en campo cercano (`near_field_mode="prism"`)

`_magnetic_prism_kernel:182`. TMI de un prisma uniformemente magnetizado en
`M = κ·(B₀/µ₀)·f̂`, proyectada sobre el campo ambiente:

```
ΔT/κ = D · f̂ᵀ T f̂
```

`T` es el tensor simétrico de segundas derivadas del potencial newtoniano `∫(1/r)dV`
(Bhattacharyya 1964; Sharma 1966; Blakely 1995 cap. 9), por suma con signo sobre las 8
esquinas con `µ = (−1)^{i+j+k}`:

```
T_xx = −Σ µ·atan2(y·z, x·r)      T_xy = Σ µ·ln(r + z)
T_yy = −Σ µ·atan2(x·z, y·r)      T_xz = Σ µ·ln(r + y)
T_zz = −Σ µ·atan2(x·y, z·r)      T_yz = Σ µ·ln(r + x)

proj = f_x²T_xx + f_y²T_yy + f_z²T_zz + 2(f_x f_y T_xy + f_x f_z T_xz + f_y f_z T_yz)
```

**La prueba de consistencia de los signos**: en campo lejano
`T_ij → V·(3d_i d_j − r²δ_ij)/r⁵`, de modo que `f̂ᵀTf̂ → V·(3cos²θ−1)/r³` y
`D·f̂ᵀTf̂ → C·(3cos²θ−1)/r³` — recupera **exactamente** el dipolo, mismo signo y misma
escala. Hay un test de campo lejano que lo verifica; el signo global se reabsorbe en
`sign = −((−1)^{i+j+k})` justamente por eso. El dipolo puro sobre o subestima la amplitud en
cuerpos someros porque ignora la extensión finita del vóxel.

#### Remanencia (Fase 12)

`build_kernel_with_remanence:451`. Kernel total `J = J_ind + Q·J_rem`: se reconstruye
`G_rem` con la dirección `(I_rem, D_rem)` reusando las listas de vecinos del KDTree ya
calculadas, y se devuelve `G_ind + q_ratio·G_rem`. Con `q_ratio = 0` devuelve `G_ind` sin
coste extra. `sweep_q_ratio:2871` barre Q cuando el usuario no lo conoce.

#### MVI — inversión de magnetización vectorial (Fase 20C)

`build_mvi_kernels:519`. En vez de asumir `M ∝ f̂`, se computa la sensibilidad TMI a cada
componente cartesiana:

```
ΔT = Σ_c M_c · G_c ,      G_c = C·[ 3·r_c·(f̂·r_vec)/r⁵ − f̂_c/r³ ],   c ∈ {x,y,z}
```

**Gate de consistencia (Paso 1 de la fase)**: fijando `M = κ·f̂` (inducción pura),

```
Σ_c f̂_c·G_c = C·[3(f̂·r_vec)²/r⁵ − 1/r³] = C·(3(f̂·r_vec)² − r²)/r⁵
```

que es **exactamente** el kernel escalar TMI. Reproduce el escalar a precisión de máquina
(Lelièvre & Oldenburg 2009; Ellis et al. 2012).

#### Gradiometría de tensor (Fase 1.4)

`build_gradient_tensor_kernels:629`. Derivadas espaciales `∂B_i/∂x_j` (nT/m) respecto de la
posición del sensor. Mayor resolución espacial y **sin** necesidad de remoción regional ni
corrección de deriva de base.

#### Un modo declarado que el motor RECHAZA a propósito

`reject_unavailable_inversion_modes` (`geophysics_service.py:551`). El esquema acepta
`remanence.inversion_mode="amplitude"` y el reporte lo transcribía, pero **ningún** solver de
producción lo ejecutaba: el despacho sólo tenía rama para `total_field`. El resultado era un
reporte que declaraba una física distinta de la aplicada — corrupción de la **procedencia**.

No se cableó, y la razón está medida: `solve_amplitude_inversion_lsqr` existe y tiene tests,
pero su contrato de entrada es la **amplitud** `|B| = √(Bx²+By²+Bz²)` del campo anómalo
(≥ 0), mientras que producción sólo transporta TMI, que es una **proyección con signo**.
Convertir TMI → |B| exige una transformación de componentes (dominio de Fourier / señal
analítica) que no existe en el repositorio. Alimentar el solver con TMI sería el mismo
pecado con otro disfraz. Hasta entonces, el modo **se rechaza en voz alta**.

---

## 6. El problema inverso

### 6.1 Qué se minimiza, exactamente

El sistema aumentado que arma `solve_inversion_lsqr` (`exploration/gravimetry.py:3077`,
ensamblado en `_lsqr_ensamblar_sistema:2338`) es, en la variable escalada `m̃` con
`m = W_s·m̃`:

```
minimizar   ‖ W_d·G·W_s·m̃ − W_d·d ‖²                          ← datos
          + ‖ λ_sp · L · W_s·(m̃ − m̃_ref) ‖²                   ← suavidad (curvatura)
          + ‖ diag(w_small) · (m̃ − t_small) ‖²                 ← smallness
          + ‖ B_k · W_s · m̃ − rhs_k ‖²   (k = bloques extra)   ← cross-gradient, PGI, geología
   sujeto a   lb̃ ≤ m̃ ≤ ub̃
```

y la densidad física final es `ρ = base_density + W_s·m̃`, recortada al box
`[density_min, density_max]`.

Cada pieza, en orden.

### 6.2 Pesado de datos (σ y `W_d`)

`resolve_sigma` / `sigma_adaptive` (`potential_field_core.py:84-155`).

Hay un **centinela histórico**: `(noise_floor, noise_pct) == (0.02, 0.02)` significa «no me
declararon el ruido, calíbralo con la amplitud del dato».

**Ruta adaptativa** (Li & Oldenburg 1998 / SimPEG), invariante de escala:

```
σ_i = max(0,02·|d_i| ,  0,01·rango)
```

Versión robusta (Fase 18), cuando `detect_outliers=True`:

- outlier ⟺ `|d − mediana| > 3 · 1,4826 · MAD`
- los outliers se **downpesan 10×** (σ más permisiva) para que no dilaten σ global
- el `rango` se calcula con percentiles **p5–p95** en vez de min–max cuando hay outliers

*Caveat declarado en el propio código*: el downweighting 10× es **heurístico**. Para surveys
muy anómalos (> 10 % outliers) hay que inspeccionar el CSV o bajar el umbral.

**Ruta paramétrica**, cuando el usuario declara ruido: `σ_i = max(noise_floor, noise_pct·|d_i|)`.

**Asimetría deliberada y visible**: gravimetría trae `detect_outliers=True` por defecto y
magnetometría `False`. Cuando la Fase 7 unificó la aritmética en el núcleo compartido, la
firma quedó **sin defecto a propósito** para que unificar a uno de los dos no cambiara en
silencio el σ del otro; la asimetría vive en dos wrappers finos, donde se ve
(`gravimetry.py:104`, `magnetometry.py:108`).

**De dónde sale σ en producción** (`_seleccionar_lambda_y_sigma:3660`), en orden de
prioridad:

1. `noise_floor_mgal` declarado (o σ por estación desde el CSV) → piso paramétrico,
   convertido mGal → m/s² con `×1e-5`.
2. `gravimeter_type` conocido → tabla instrumental `GRAVIMETER_NOISE_FLOOR`
   (`core/config.py:190`): Scintrex CG-6 **0,005 mGal**, ZLS Burris **0,002**,
   LaCoste-Romberg **0,010**, desconocido **0,020**. `noise_pct = 0`, piso puro → χ²_red
   **interpretable contra el ruido real del instrumento**.
3. Nada de lo anterior → centinela adaptativo.

Esa distinción es la que decide si Morozov es aplicable (§6.7).

Después: `W_d = diag(1/σ)`, `G_w = W_d·G`, `d_w = W_d·d`.

### 6.3 El peso de modelo `W_s` — la pieza central, y el hallazgo H-1/H-33

`build_model_weights` (`potential_field_core.py:317`) es **el único sitio** donde se elige
el peso de modelo. Hay dos:

| tipo | fórmula | quién lo usa |
|---|---|---|
| `sensitivity` | `diag_j = 1 / max(‖col_j(W_d·G)‖, 1e-12)` | **gravimetría** |
| `depth_li_oldenburg` | `diag_j = (z_j+z₀)^{+β/2}`, normalizado a media 1 | magnetometría |

**La regla, en una línea** (`potential_field_core.py:26-32`): un peso `W` que multiplica
*todos* los bloques del sistema aumentado es un **cambio de variable puro** y no cambia la
solución física; sólo actúa si algún bloque —en la práctica, la smallness— queda **sin** él.

Esa regla explica el defecto que H-33 midió: **el mismo parámetro `depth_beta` tiene tres
comportamientos** según qué opciones estén activas, y nadie elegía cuál:

| motor / ruta | ¿`depth_beta` actúa? | por qué |
|---|---|---|
| Gravimetría (grilla regular) | **nunca** | el peso de modelo es `‖col‖` |
| Magnetometría ruta A (sin padding, sin anclajes, L2) | **sí** | la smallness NO lleva `W` |
| Magnetometría ruta B (producción) | **no** | todos los bloques llevan `W` |

Y en gravimetría, el bloque que decía implementar «W_z formal (Li & Oldenburg 1998)» no lo
implementaba. La demostración, en tres líneas (`gravimetry.py:2265-2280`):

```
Wz_inv    = diag((z+z₀)^{+β/2})                  ← el "depth weighting"
Ws        = diag(1/‖col_j(G_w·Wz_inv)‖)          ← se calculaba DESPUÉS
          = diag(1/(w_j·‖col_j(G_w)‖))
Wz_inv·Ws = diag(1/‖col_j(G_w)‖)                 ← w_j se CANCELA
```

`Ws` se computaba sobre el kernel ya pesado por `Wz`, deshaciendo exactamente lo que `Wz`
acababa de hacer. Medido a precisión de máquina (1,7e-16) y luego E2E: mover β de 0 a 4
cambiaba la solución 2,5e-04 con TRF y 5,2e-06 con LSQR+GPCG — es decir, un residuo de
**parada temprana** (dependiente del solver), no un efecto físico.

**Lo que el código aplica de verdad:**

```
φ_smallness = λ_eff² · Σ_j ( ‖col_j(W_d·G)‖ · m_j )²
```

una ponderación por **sensibilidad**. Medida sobre la malla del producto, esa norma de
columna resulta ser una **ley de potencia limpia** (desviación máxima 5,3 %) equivalente a un
Li & Oldenburg de **β ≈ 2,63** — la misma familia que el estándar industrial β = 2, algo más
agresiva. El problema no es que el peso tenga mala forma: es que **no es ajustable y no
estaba declarado**; lo fija el kernel, no una decisión.

`ModelWeights.effective_depth_exponent` (`potential_field_core.py:285`) mide eso **en cada
corrida** en vez de citar el número histórico:

```
u_j = 1/diag_j  (peso de penalización físico)
Li & Oldenburg: u_j ∝ (z_j+z₀)^{−β/2}
⇒ β = −2 · pendiente( log u  vs  log(z+z₀) )
```

y publica también la desviación relativa máxima, que es la que responde «¿es una ley de
potencia limpia?».

`Ws` conserva además un papel algebraico legítimo: sin él, λ = 3,0 domina los datos ~14.000×
en magnitudes SI y se pierde la calibración `N_CALIB = 256`.

**Por qué no se separó.** La Fase 4 midió la alternativa (`Ws` como precondicionador global
y `(z+z₀)^{−β/2}` como peso explícito) en **3.450 inversiones** con Morozov re-eligiendo λ en
cada brazo. Conclusión: **ningún β fijo** mejora la profundidad en todos los regímenes; el
techo es null-space, no el peso. Se decidió NO cablearla. En el Octree,
`solve_inversion_treemesh`, β **sí está vivo**.

**No confundir con el peso de FILA.** `depth_row_weights`
(`potential_field_core.py:368`):

```
w_reg = 1/(z+z₀)^β , normalizado a media 1
```

multiplica las **filas** de un bloque de regularización (relaja la penalización en
profundidad) y **no se deshace** al destransformar, porque no es un cambio de variable. Lo
usan la σ posterior, los dos live-update y los dos selectores de λ. Que las dos cosas se
llamasen «depth weighting» es la raíz de H-33.

### 6.4 Regularización espacial: el Laplaciano

`_build_laplacian` (`gravimetry.py:1291`). Laplaciano de grafo 3D **sin wrap-around**, en
orden F.

- Grilla uniforme: peso de arista `w_ij = 1`.
- Grilla no uniforme: `w_ij = 2/(h_i + h_j)`, donde `(h_i+h_j)/2` es la distancia real entre
  centros de celdas adyacentes.

Convención de signos, `L = W − D`: off-diagonal `L[i,j] = w_ij ≥ 0`, diagonal
`L[i,i] = −Σ_j w_ij`. La regularización `‖λ·L·m‖² = λ²·mᵀL²m` es equivalente al Laplaciano
estándar `(D − W)` porque `L² = (−L_std)² = L_std²`.

Propiedades verificadas (Fase 17, `tests/test_laplacian_*.py`):

- Convergencia `L_nu → (1/h₀)·L_u` cuando `hx → h₀` (error < 1e-10).
- Equivalencia de inversión con λ escalado (error < 1e-5).
- Propiedades de M-matriz: simetría, suma de filas ≈ 0, signos correctos.
- Fórmula por arista `w_ij = 2/(h_i+h_j)` exacta.
- Anisotropía reflejada: pesos X ≠ Y cuando `hx ≠ hy`.
- TreeMesh: el Laplaciano octree converge en ≤ 20 iteraciones LSQR.

El peso de la suavidad es:

```
λ_spatial = alpha_spatial · (n_sensores / n_activas)
```

Se diagnostica cuando queda `< 1e-4` (`geophysics_service.py:3711`), porque en grillas
grandes con pocos sensores el ratio puede ser ≪ 1 y la suavidad deja de actuar.

**Relajación local en vóxeles anclados (Fase 8):** las filas de `L` correspondientes a
celdas con sondaje se escalan por `laplacian_relax_alpha < 1`. Reduce el acoplamiento de
suavidad que esas celdas imponen sobre sus vecinas (mitiga halos y bullseyes); el valor del
sondaje lo fija el término de smallness con κ, no el suavizado. Es un row-scaling diagonal:
conserva la estructura CSR y no altera `cond(A)` materialmente.

### 6.5 Smallness, modelo de referencia, padding, anclajes y bounds

**Calibración de λ.** `lambda_mag_eff = lambda_mag · √(n_active_sol / 256)`. El 256 es
`N_CALIB`, y el escáner de λ de diagnóstico **no lo aplicaba** — parte del desfase medido en
§6.7.

**Pesos de la smallness por celda** (`_mk_small`, `gravimetry.py:2688`):

```
w_j = λ_eff                                 celda normal
w_j = padding_kappa · λ_eff                 celda de padding
w_j = anchor_kappa · λ_eff                  celda anclada (modo soft)
w_j = 0                                     celda anclada (modo hard: la variable ya no existe)
w_j ·= focus_w_j                            si IRLS compacto está activo y la celda es libre
```

**Modelo de referencia `m_ref`.** Entra por dos canales distintos y **no son equivalentes**:

1. *Suavidad* (Li & Oldenburg 1999 tal como estaba): residual
   `λ_sp·L·(m − m_ref)`, RHS `d_reg = λ_sp·(L·m_ref)`.
2. *Smallness* (Fase 14): bloque aditivo `√α·I` con RHS `√α·m_ref`, o sea `α‖m − m_ref‖²`
   **encima** del smallness hacia 0.

La diferencia se midió, no se supuso. `L` es un Laplaciano de grafo: sólo actúa sobre la
**curvatura** del contacto, mientras el smallness sigue tirando de cada celda hacia
`base_density`, es decir **contra el prior**. Sobre un dique inclinado con anti-inverse-crime
×3 y semillas pareadas:

- por la **suavidad**, el prior geológico **empeora** la recuperación (PR-AUC 0/25 semillas);
- por el **smallness**, la **mejora** en las cuatro métricas y en todas las semillas, y su
  control con geología **FALSA** pasa a ser el **peor** brazo de todos — que es la firma de
  una restricción que de verdad transporta información geológica.

`geo_prior_alpha = 0` → no se apila nada → byte-idéntico al comportamiento histórico.

**Anclaje de sondajes.** Dos modos:

- *Soft*: `w_j = anchor_kappa·λ_eff` con target
  `t_j = contraste_medido_j / diag(W_s)_j`. La división por `diag(W_s)` es obligatoria: el
  bloque smallness opera en `m̃` mientras el contraste vive en unidades físicas. Sin ella, la
  densidad recuperada queda en `base + diag·contraste ≈ base` — el bug medido E2E en la
  Fase 25 (`gravimetry.py:2455-2470`).
- *Hard* (Fase 2.1): **eliminación de variables**. Se mueve `G_aug[:,j]·t_j` al RHS, se anula
  la columna `j` con un `diags((~anchor).astype(float))`, y tras resolver se reinyecta
  `m̃_j = t_j` exacto. Sin el ~2 % de error residual del soft.

**Bounds.** El box físico `[density_min, density_max]` se lleva a `m̃` con la **misma
biyección** que recupera la densidad, y es exacta:

```
lb̃_j = (density_min − base_density) · ‖col_j‖
ub̃_j = (density_max − base_density) · ‖col_j‖
```

**Bounds por unidad litológica** (Fase 2.3): en las celdas con litología conocida, el box
escalar global se reemplaza por el `[dens_min, dens_max]` de su unidad, transformado igual.
El solver con bounds (TRF o FISTA proyectado) lo impone satisfaciendo KKT por celda. La tabla
por defecto vive en `exploration/pgi_engine.py:47` (granite 2,52–2,75; gabbro 2,85–3,12;
magnetita, etc., de Telford 1990 / Clark 1997 / Hunt 1995) y el usuario puede sobrescribirla.

> **Defecto medido, NUEVO-8 / Fase 20:** dos de los tres presets de litología imponen un
> piso de contraste **positivo** (magnetita +1,90 t/m³) que deja la roca caja **fuera** de la
> caja permitida y clava el **76,20 %** de las celdas al bound. `build_effective_contrast`
> (`geophysics_service.py:470`) publica ese contraste efectivo en vez de esconderlo.

### 6.6 Norma de regularización: L2, compacta y mixta

`regularization_norm ∈ {"l2", "compact", "mixed"}` (`_lsqr_resolver_irls:2650`).

- **L2**: un único solve, byte-idéntico al motor histórico. `n_irls = 1`, sin foco.
- **compact**: IRLS de **minimum support** (Portniaguine & Zhdanov 1999) sobre la smallness.
- **mixed**: además un término de suavidad *edge-preserving*.

El foco se calcula sobre el **contraste físico** `c = W_s·m̃` (t/m³), no sobre `m̃`:

```
f_i = 1/√(c_i² + ε²) , normalizado a media 1 sobre las celdas libres
```

Concentra la penalización donde `c ≈ 0` (vacía el fondo) y la relaja donde hay cuerpo (lo
deja crecer) → cuerpos compactos y nítidos. La **normalización a media 1 conserva la magnitud
global** de la regularización: redistribuye el foco sin degradar el misfit.

`ε` se **enfría** por iteración (`ε ← max(0,7·ε, ε_floor)`, con `ε_floor = max(compact_eps, 1e-3)`)
para endurecer progresivamente el foco. Se para cuando el cambio relativo del vector de foco
cae por debajo de `compact_tol`, o al agotar `compact_max_irls`.

Las **celdas libres** excluyen padding y anclajes: esos conservan su papel de restricción
fuerte L2.

En modo `mixed` se apila además `0,5·diag(r)·(λ_sp·L·W_s)` con
`r = clip(1/√(g²+ε²) / media, 0,05, 20)` y RHS 0 — refuerza la suavidad donde el modelo es
plano y la relaja en los bordes. El factor 0,5 evita sobre-suavizar, porque la suavidad base
ya vive en `G_aug`.

Medido: el IRLS compacto mejora la localización **+50,6 %** (Fase 24B).

### 6.7 Elección de λ — tres estrategias, y por qué producción usa la que usa

#### (a) Punto de operación fijo, precondicionado

Cuando `auto_lambda=True` o `lambda_mag == 0` y el σ **no** es explícito, se usa
`PRECONDITIONED_OPERATING_LAMBDA`. La justificación escrita en el código
(`geophysics_service.py:3688`): el problema es **subdeterminado**, y los selectores guiados
por dato (L-curve, χ²-target, GCV) **sub-regularizan**. El óptimo en espacio precondicionado
es O(1–10), validado contra verdad sintética (λ ≈ 3 → Pearson ≈ 0,95).

#### (b) Discrepancia de Morozov sobre el solver REAL

Se activa **sólo** si σ es explícito (`noise_floor_mgal` declarado o gravímetro conocido),
porque sólo entonces χ²_red es físicamente interpretable.

`_ejecutar_solver:4046`:

- Candidatos `[0,01 · 0,05623 · 0,31623 · 1,77828 · 10,0]` = `logspace(-2, 1, 5)`.
- Cada candidato es **un solve completo de producción** (kernel cacheado ⇒ coste ≈ 1 solve).
- Se elige el de `|log₁₀(χ²_red)|` mínimo y se **adopta directamente esa solución**.
- Bisección geométrica del bracket de χ² = 1 (χ² crece con λ): 1 solve extra. **≤ 6 solves
  en total.**
- Avisos honestos: `morozov_underfit_floor` si ni λ=0,01 alcanza χ² ≤ 1 (el dato no es
  ajustable al nivel del σ declarado); `morozov_overfit_ceiling` si incluso λ=10 da χ² < 1
  (σ declarado probablemente mayor que el ruido real).

**Detalle de refactor que sólo destapó el arnés de byte-identidad** (`:4160-4168`): Morozov
**reelige** λ, y en el monolito esa reasignación era visible para todo lo que venía después
(PGI, DOI, checkerboard, σ posterior, reporte). Al partir la función eso dejó de ser
automático, y hubo que escribirlo de vuelta explícitamente. Sin esa línea, el refactor sería
«mismo código, otra λ».

#### (c) L-curve y χ²-target (diagnóstico, NO producción)

`select_lambda_lcurve:1416` y `select_lambda_chi2_target:1674`.

Aquí vive una de las lecciones más caras del proyecto. Estos escáneres armaban un funcional
**distinto** del que resuelve el solver. La Fase 4 quitó `w_reg` del solver (midió que ahí
`Ws` cancelaba el peso) y **nadie actualizó los escáneres**: el desajuste que un comentario
documentaba haber arreglado **había vuelto, callado, por el mismo mecanismo**.

Medido con `scripts/validation/fase7_lambda_identity_probe.py`, cuerpo sintético con Morozov
re-eligiendo λ en cada profundidad:

| profundidad | χ² prometido | χ² real del solve | ratio |
|---|---|---|---|
| 150 m | 2,084 | 48,53 | **23×** |
| 350 m | 0,444 | 128,5 | **289×** |
| 550 m | 0,0724 | 165,7 | **2.290×** |
| 750 m | 0,0161 | 204,5 | **12.700×** |

y en **0 de 4** casos el λ elegido fue el que el solver real habría elegido. El error **crece
con la profundidad**, que es justo donde los dos funcionales más difieren.

Hoy el trial arma exactamente los tres bloques de `solve_inversion_lsqr`: datos `W_d·G·W_s`,
suavidad `λ_sp·L·W_s` (sin `w_reg`) y smallness **identidad en m̃** con
`λ_eff = λ·√(n/256)`, incluida la calibración `N_CALIB`. Es la reparación del **instrumento
de diagnóstico**: un instrumento que mide con el operador equivocado es una trampa, no un
instrumento.

El χ²-target es el principio de discrepancia de Morozov con la restricción de estabilidad
`cond(A) < cond_max` (por defecto 1e12) usando el estimador de `cond(A)` de LSQR.

**Fragilidad conocida de Morozov en profundidad**: `χ²(λ)` se aplana (4,06 → 1,27 → 0,56) —
eso **es** el null-space. Morozov rescata el régimen moderado (150–300 m), no el profundo.

### 6.8 El despacho del solver — lo que PASA, no lo que se pide

`_lsqr_despachar_solver:2515`. Reglas, en orden:

```
use_trf  = USE_BOUNDED_SOLVER  and  n_active_sol ≤ 8.000
use_lsmr = (not use_trf) and USE_LSMR_LARGE and n_active_sol > LSMR_THRESHOLD (50.000)
else       LSQR + clip
```

| solver | cuándo | qué es |
|---|---|---|
| **TRF/bounded** | ≤ 8.000 celdas | `scipy.optimize.lsq_linear` con `method='trf'`, `lsq_solver='lsmr'`, `tol=1e-6`, `max_iter=300`. Bounds reales |
| **LSMR** | > 50.000 celdas | Fong & Saunders (2011): ‖r‖ monótonamente decreciente, mejor estabilidad que LSQR en sistemas mal condicionados. **No** forma `AᵀA` |
| **LSQR + clip** | resto | `iter_lim=500`, `atol=btol=1e-8`, `damp=0`, luego `np.clip` a los bounds |

Benchmark que fijó el umbral 8.000: TRF+LSMR ~40 s con NNZ ≈ 213K y `n_active` ≈ 14K; LSQR
< 0,1 s.

**FISTA proyectado** (`USE_PROJECTED_SOLVER`, por defecto ON): tras LSQR/LSMR+clip, refina
con gradiente proyectado acelerado partiendo del clip como warm start, así que el objetivo
sólo puede mejorar. El clip post-hoc descarta masa fuera del box **sin redistribuirla**
(misfit degradado ~35 % en cuerpos compactos). Medido en la sonda de liveness (384 celdas): con
`USE_PROJECTED_SOLVER=false` el χ² final pasó de **0,244 a 22,7 (93×)**. No es una preferencia
de solver: es la diferencia entre ajustar el dato y no ajustarlo.

**El defecto de honestidad que esto cerró (Fase 5, H-11):** el reporte traía
`bounded_solver_active` calculado con `os.getenv("USE_BOUNDED_SOLVER")` — o sea, **lo que se
pidió**. Medido con 8.712 celdas activas y la variable sin tocar: el solver despachó
`LSQR+clip` y el reporte afirmaba `true`. No es un caso de borde: el umbral son 8.000 celdas
y el producto declara mallas de 30k–100k vóxeles, así que **en el régimen normal el campo
estaba SIEMPRE mal**. Y `validation/runner.py` lo leía para caracterizar cada corrida: era
evidencia de validación contaminada. Hoy `solver_meta` publica `solver_path`,
`bounded_solver_used`, `bounded_solver_requested`, `lsmr_used`, `projected_used`.

**Otro camino que se borró en vez de arreglarse (Fase 6, H-2):** `USE_SPARSE_DIRECT`
llamaba a `solve_sparse_normal_equations`, un símbolo que **no existía en el repositorio**:
con el flag en true, la inversión abortaba con `NameError` tras construir el kernel. Se
borró porque formar `AᵀA` eleva `cond(A)` **al cuadrado**; LSMR es la respuesta correcta.

**Adaptación dinámica de κ (Fase 16):** se estima `cond(A)` por el ratio max/min de las normas
de columna al cuadrado (`estimate_cond_from_columns`, O(nnz), sin SVD). Si `cond > 1e12` y
`auto_kappa=True`, se escalan `padding_kappa` y `anchor_kappa` por `1e12/cond` y se
re-ensambla.

**Convergencia declarada:** `istop ∈ {3, 7}` de LSQR significa **no convergido** (3 = superó
`conlim`, 7 = agotó `iter_lim`). Se publica `lsqr_converged`. Importa más de lo que parece:
cuando el peso de modelo es un cambio de variable puro es también un **precondicionador por
la derecha**, y un precondicionador sólo es inocuo si el solver **llega**. Si trunca, cambia
el punto de parada, y entonces un parámetro «inerte» mueve el resultado igualmente.

**Cuantificado (Fase 7).** En la ruta B magnética la solución **exacta** (`lstsq` denso) es
invariante en β a **1e-11** — el álgebra de H-33 es correcta — pero el solve iterativo
termina con `istop=7` en **500/500** para todo β, y queda a **54 %–269 %** de la exacta. Mover
β de 0,5 a 3,0 cambia la susceptibilidad recuperada un **66 %–86 %**. No es redondeo: es casi
toda la señal, y viene de **dónde se detiene el solver**.

Por eso `declare_functional` (`potential_field_core.py:404`) publica, por corrida:
`depth_beta_has_effect` y `effect_mechanism ∈ {functional, early_stopping, none}`. Declarar
«inerte» cuando el solver truncó sería exacto sobre el álgebra y **falso sobre la corrida**.

`iter_lim=500` es una decisión medida (`fase8_iter_lim_probe.py`): en gravimetría el límite
**no ata** (delta 0 exacto entre 500 y 5000); en magnetometría subirlo mueve el modelo hasta
66 % por el espacio nulo **sin mejorar el χ²**, que ya está en 1e-14.

### 6.9 Inversión conjunta (joint)

`services/joint_inversion.py`. Esquema de **Gauss-Newton alternado** (sequential,
Gallardo–Meju) con *continuation strategy* exponencial sobre el peso del acoplamiento.

#### Cross-gradient

El cross-gradient `t = ∇m_ρ × ∇m_χ` se anula cuando los gradientes son **paralelos**, es
decir cuando ambos modelos comparten **estructura** (bordes en los mismos sitios), sin
imponer ninguna relación petrofísica entre los **valores**. Se linealiza fijando un modelo y
penalizando el otro:

```
paso de gravedad:      min ‖ ∇m_ρ × ĝ_χ ‖
paso de magnetometría: min ‖ ∇m_χ × ĝ_ρ ‖
```

El bloque disperso `B` (3·nC × nC) tal que `B·m = ∇m × ĝ` (`_build_cross_gradient_block:112`):

```
t_x = (∂y m)·ĝ_z − (∂z m)·ĝ_y    ⇒  B_x = diag(ĝ_z)·D_y − diag(ĝ_y)·D_z
t_y = (∂z m)·ĝ_x − (∂x m)·ĝ_z    ⇒  B_y = diag(ĝ_x)·D_z − diag(ĝ_z)·D_x
t_z = (∂x m)·ĝ_y − (∂y m)·ĝ_x    ⇒  B_z = diag(ĝ_y)·D_x − diag(ĝ_x)·D_y
```

`ĝ = ∇m/√(gx²+gy²+gz²+1e-12)` es **adimensional y escala-invariante**: por eso el
acoplamiento no depende de que ρ (~t/m³) y χ (~SI) tengan magnitudes muy distintas.

#### Gramian (Zhdanov)

`_fixed_gradient_dirs:96` con `kind="gramian"` usa el gradiente **crudo** `∇m` en vez del
unitario: el acoplamiento queda ponderado por la magnitud del gradiente del modelo fijo, de
modo que el producto cruzado enfatiza el alineamiento donde el contraste fijo es **fuerte**
(bordes nítidos) y lo relaja donde es plano. Mismo patrón disperso, distinta normalización.

#### Métrica de parada

Hay dos, y sólo una sirve:

```
E_l2   = ‖∇m_ρ × ∇m_χ‖₂ / (‖∇m_ρ‖₂·‖∇m_χ‖₂ + ε)      ← fórmula literal del plan
E_cell = Σ‖∇m_ρ × ∇m_χ‖ / Σ(‖∇m_ρ‖·‖∇m_χ‖ + ε)        ← la que se USA
```

`E_l2` **satura en ≈ 1/√N** para campos distribuidos sobre N celdas (verificado: gradientes
ortogonales en TODA celda → `E_l2 = 1/√N`), porque el denominador multiplica energías
**totales** —con términos cruzados entre celdas lejanas— mientras el numerador suma
productos **locales**. Un umbral absoluto sobre ella sería dependiente de la malla. Se
conserva sólo por trazabilidad con el plan.

`E_cell` es el análogo local: media ponderada por magnitud de `sin(ángulo)` entre gradientes,
rango real `[0,1]` independiente de N. Las celdas planas pesan ≈ 0 de forma natural.

#### PGI conjunto (Astic & Oldenburg 2021)

A diferencia del cross-gradient, el PGI conjunto acopla los **valores**: una mixtura
gaussiana 2D en el plano (densidad, susceptibilidad) cuyas clases tienen centroides
correlacionados (por ejemplo magnetita = alta ρ **y** alta χ). En cada iteración cada celda
se asigna por MAP a su clase 2D y se la empuja con un término smallness hacia el centroide de
esa clase **en ambas físicas a la vez**. El bloque reutiliza el hook `extra_reg_blocks`:
`A_pgi = √α·I` en espacio físico con RHS `√α·m_ref`.

El GMM puede ser **dinámico** (refit NIW con priors `prior_kappa`, `prior_nu`,
`weight_concentration`) o fijo desde la tabla `DEPOSIT_GMM_DEFAULTS`
(`exploration/pgi_engine.py:22`): pórfido Cu, VMS Cu-Zn, skarn Fe, IOCG, cada uno con 3
componentes (media, σ, peso) en t/m³.

**Ganancia E2E del joint frente al cross-gradient: no demostrada** (registro de la F3).

#### Cómo entran los bloques externos al motor

`inject_extra_reg_blocks` (`potential_field_core.py:741`). Los bloques llegan en **espacio
físico** del modelo; el solver trabaja en `m̃` con `m = W_s·m̃`, así que cada bloque `B` se
convierte en `B·W_s` (igual que `L_scaled = L_active·W_s`). El RHS se apila tal cual, porque
vive en el espacio de residual del bloque. El caller recorta `B[:, obs_mask]` antes de pasar,
para que `B.shape[1] = n_active_sol` tras la poda observable.

### 6.10 Geología implícita (HRBF)

`exploration/implicit_modeling.py`. Campo escalar implícito `φ(x)` cuyo nivel cero es la
superficie geológica y cuyo signo etiqueta unidades, construido por **HRBF** (Hermite Radial
Basis Function implicits, Macedo et al. 2011) con kernel triarmónico `ψ(r) = r³` (C², gradiente
suave en `r→0`) más deriva polinómica de grado 1. Interpola **simultáneamente** valores de φ
(dentro/fuera/sobre la superficie, desde contactos de sondaje) y **gradientes** de φ (normales
= polos a la estratificación, desde medidas estructurales de orientación). Es la formulación
de *potential field* / dual-cokriging que usan GemPy y LoopStructural, implementada con numpy
puro.

Se convierte en `m_ref` y entra al solver por el término de **smallness** (§6.5).

**Límites honestos declarados en el propio módulo**: no se cablea al solver como level-set
inversion; no integra fallas ni cokriging bayesiano; el modelo categórico es binario; y con
contactos a una sola cota el HRBF **degenera a un plano** (medido en la Fase 14).

---

## 7. Incertidumbre y no-unicidad

Esta es la sección donde el producto se distingue: hay **cinco** mecanismos distintos, cada
uno mide una cosa distinta, y ninguno pretende ser lo que no es.

### 7.1 Lo que NO es una probabilidad

`_lsqr_reconstruir_salida:2969`. El campo histórico `probability` que consume el frontend es:

```
score_j = 1 − |Gᵀ·residual|_j / max_j |Gᵀ·residual|
```

Es un **score de ranking normalizado [0,1]** derivado del residual proyectado al modelo: mide
cuán bien explicado queda cada vóxel relativo al peor vóxel. Sirve para **ordenar**
objetivos, no para afirmar confianza estadística. En el payload se expone también con su
nombre canónico, `relative_target_score`.

Con datos degenerados (`max_voxel_error ≤ 0`) devuelve **NaN**, no 1,0 — porque un 1,0 fingiría
calidad máxima.

Igual con el misfit: si `‖d_obs‖ ≤ 0` o no es finito, `misfit_percent = NaN` en vez de fingir
ajuste perfecto.

### 7.2 σ posterior lineal (Hutchinson)

`estimate_posterior_std:3301` + `hutchinson_diag_inv:253`.

Bajo el modelo lineal gaussiano del problema inverso regularizado, la covarianza posterior en
el espacio escalado es:

```
C̃ = ( GsᵀGs + λ_sp²·LsᵀLs + λ_mag²·I )⁻¹
```

con `Gs = W_d·G·W_s` y `Ls = W_m·W_s` — **exactamente** los operadores que arma
`solve_inversion_lsqr`. La diagonal se estima por Hutchinson:

```
diag(A⁻¹) ≈ (1/N) Σ_k  z_k ⊙ (A⁻¹ z_k),      z_k ~ Rademacher (±1)
```

Es **insesgado**, porque `E[z zᵀ] = I`, y el error decae como `O(1/√N)` (Bekas, Kokiopoulou &
Saad 2007). Cada `A⁻¹z_k` se resuelve por **gradiente conjugado** con precondicionador de
Jacobi, sin formar `A⁻¹`. Escala a problemas grandes.

Se deshace el column scaling para volver a unidades físicas:

```
σ_phys_j = W_s,jj · √(diag(C̃)_j)      [t/m³]
```

`λ_mag > 0` es obligatorio: es lo que garantiza que `C` sea definida positiva.

**Alcance honesto, escrito en el docstring**: es la covarianza posterior **lineal** alrededor
de la solución regularizada. **No** captura la no-unicidad no lineal, ni el error de
modelo/topografía, ni el sesgo de profundidad inherente. Debe reportarse como «σ posterior
lineal», no como verdad absoluta.

### 7.3 DOI — profundidad de investigación (Li & Oldenburg 1999)

`_doi_doble_inversion:4720`. Dos inversiones con modelos de referencia distintos:

```
m₁ con m_ref1        (idéntica a la corrida principal)
m₂ con m_ref2 = m_ref1 + 0,1 t/m³

DOI_j = |m₁_j − m₂_j| / max(|m_ref1_j − m_ref2_j|, 1e-12)
```

Sólo se ejecuta **una** inversión extra, porque la inversión 1 *es* la corrida principal. La
diferencia cancela la densidad base. DOI ≈ 0 significa «el dato manda aquí»; DOI ≈ 1
significa «aquí manda la referencia», o sea que la celda no está restringida por el dato.

**Detalle que la Fase 14 tuvo que arreglar**: la pass-2 debe llevar **exactamente** el mismo
binding que la pass-1 (mismos anclajes, mismo `anchor_mode`, mismos bounds litológicos, mismo
`geo_prior_alpha`, misma λ auto-seleccionada). Si la pass-1 lleva el bloque de smallness
geológico y la pass-2 no, la diferencia mezcla el desplazamiento de referencia —lo único que
el DOI quiere medir— con el cambio de funcional, y el índice sale **inflado sin que nada
avise**.

Es no-fatal: si revienta, `doi_raw` queda en NaN y la corrida sigue.

### 7.4 Null-space shuttle (Fase 8.1)

`null_space_shuttle_directions:308`. Mide la cara de la incertidumbre que la σ posterior **no
ve**: la no-unicidad.

```
δ = s − G⁺(G s) ,      G⁺ = (GᵀG + µ²I)⁻¹Gᵀ
```

`G⁺(Gs)` es la componente de una dirección aleatoria `s` que el **dato resuelve**; al restarla,
`δ` es justo la parte que el dato **no** restringe. Con `µ→0`, `δ` tiende a la proyección
exacta sobre `null(G)`; `µ` pequeño la estabiliza. Referencias: Deal & Nolet (1996), Fichtner
& Zunino (GJI 2018).

`smooth_op` (por ejemplo `(I + γLᵀL)⁻¹`) suaviza `s` **antes** de proyectar, para que las
alternativas sean geológicamente plausibles (campos correlacionados) y no ruido sal y
pimienta. El shuttle «viaja» por modelos lisos.

Se devuelven dos diagnósticos, y el segundo es el que importa:

- `preserved = ‖Gδ‖/‖Gs‖` — cuánto preserva el ajuste de datos la alternativa. Idealmente ≈ 0.
- `null_fraction = ‖δ_cruda‖/‖s‖` **antes** de normalizar — cuánta de la dirección aleatoria
  sobrevive a la proyección, es decir **cuánto espacio nulo hay**. ≈ 0 ⇒ el dato lo resuelve
  todo; O(1) ⇒ gran no-unicidad. Distingue «núcleo grande» de «núcleo nulo», algo que
  `preserved` (≈ 0 en ambos casos) no puede.

Todo matrix-free por CG. **Alcance honesto**: muestreo de la no-unicidad **lineal**, no un
posterior bayesiano. Los peldaños superiores (SVGD recocido, HMC/difusión) son R&D pendiente.

### 7.5 Targeting probabilístico

`rank_drill_targets:519`. Convierte modelo + σ posterior en una **lista rankeada de blancos
perforables**. Es motor-agnóstico: sirve para densidad (t/m³) o susceptibilidad (SI).

Para cada vóxel, bajo `m_j ~ N(model_j, σ_j²)`, con `diff = ±(model_j − τ)` (el signo lo elige
`sense`: `negative` sirve para cuerpos de **bajo** contraste, como kimberlita o sal) y
`d = diff/σ_j`:

```
exceedance_prob        = Φ(d)
expected_exceedance    = σ_j·φ(d) + diff·Φ(d) = E[max(±(m−τ), 0)]
lower_confidence_bound = diff − k·σ_j
```

`expected_exceedance` es forma cerrada y es el análogo del *expected improvement* de la
optimización bayesiana: premia magnitud **y** upside exploratorio. `lower_confidence_bound`
es el score pesimista: un pico fuerte pero mal resuelto **cae**.

Umbral robusto si no se da: `τ = mediana ± 2·spread`, con `spread = 1,4826·MAD`, y con
fallback a la desviación estándar si el modelo es disperso (muchos ceros → MAD ≈ 0), porque
si no el umbral quedaría **en el fondo** y dejaría todo el fondo en `exceedance_prob = 0,5`,
volviéndolo candidato espurio.

Luego **supresión de no-máximos 3D**: greedy sobre el score, excluyendo todo candidato a menos
de `exclusion_radius` (por defecto `2,5 ×` el paso de malla) de un blanco ya elegido → blancos
**espacialmente distintos**, no 50 celdas del mismo cuerpo.

**Alcance honesto**: es un ranking defendible de **targeting/estructura** («dónde perforar»),
**no** una probabilidad de mena ni de ley.

### 7.6 Perfil de resolución (Fase 26)

`services/resolution_qa.py`. Sustituye al tablero de checkerboard histórico como señal que
manda en el veredicto.

**El problema que resolvió.** El QA de resolución de producción devolvía **el mismo número
siempre** (`pearson_r = 0,1162` idéntico a cuatro decimales) y `FAIL` en el **100 %** de las
corridas, y el veredicto lo usaba de tope duro ⇒ `HIGH` era **inalcanzable por construcción**.
El hallazgo original culpaba a la longitud de onda del tablero. Al re-medirlo contra el código
resultaron ser **tres causas independientes**, y ésa era la **menor**:

1. **Longitud de onda.** `build_checkerboard_model` alterna el signo **celda a celda**: en una
   malla de 125 m eso es un patrón de 250 m, por debajo del límite físico de un campo
   potencial. Corregirlo solo sube `pearson_r` de 0,116 a **0,247** — con el PASS en 0,60.
2. **Puntúa profundidades que ningún survey gravimétrico resuelve.** El Pearson se calculaba
   sobre la malla **entera**. El mismo tablero, mismo kernel y misma λ, puntuado sólo en la
   banda 0–250 m con bloques de 750 m, da **r = 0,70**. El examen no medía este survey: medía
   el promedio entre lo resoluble y lo que nunca lo será.
3. **Examina un solver distinto del que produjo el modelo.** El QA invertía con `lsqr(damp=λ)`
   sobre el kernel Core: sin padding, sin bounds, sin depth-weighting, sin suavidad. Medido
   sobre 17 semillas: ese solver, con **el mismo dato observado**, devuelve PR-AUC ≈ 0,040 y el
   centroide a ~90 m, donde producción devuelve PR-AUC 1,000 y el centroide a 466 m.

**Qué mide el módulo nuevo.** Un **perfil de resolución**: para cada banda de profundidad y
cada tamaño de bloque lateral `L` de una escalera declarada (`1, 2, 3, 4, 6` celdas), se
sintetiza un tablero **lateral** (alterna en x,z; constante dentro de la banda; cero fuera),
se propaga con **el mismo kernel**, se le suma ruido al **σ declarado**, y se puntúa la
correlación del **mapa en planta** (contraste integrado en profundidad) contra el patrón
verdadero. Mediana de 3 realizaciones de ruido.

De ahí sale, por banda, la **longitud de resolución**: el bloque más pequeño que se recupera
con `r ≥ 0,60`. Es **un número en metros** que el usuario compara con el tamaño del cuerpo que
busca, en lugar de un `FAIL` sin escala.

Tres decisiones, cada una medida:

- **Mapa en planta, no celda a celda.** Aísla la resolución **lateral** —la que manda el
  targeting— de la ambigüedad de profundidad, que la gravedad sola no resuelve.
- **Escalado a la amplitud de SEÑAL, no al RMS observado**:
  `rms_signal = √(max(rms_obs² − σ², 0))`. Sin esta corrección un survey ruidoso **se
  auto-aprueba**: medido, `noise_0.15` sacaba r = 0,790 con PR-AUC real de 0,010; con la
  corrección baja a 0,661.
- **Se puntúa el dominio completo, no sólo la huella del survey.** Restringir la nota a las
  columnas con estaciones encima **premia al survey que cubre menos**: medido, `span_800m`
  pasaba de 0,104 (dominio) a 0,643 (huella) con un PR-AUC real de 0,026.

El escalar que se publica es `resolvability_index`, la media de **todo** el examen. Se eligió
por **no tener ningún parámetro ajustado al resultado**. Medido sobre 75 corridas / 15
regímenes: Spearman contra PR-AUC = **+0,853** (ρ = +0,922 sobre las 15 medianas por régimen),
frente a **+0,073** de `chi2_red` y +0,275 del tablero viejo. Variantes ajustadas (una banda
concreta, un peldaño concreto) llegaban a +0,89–0,92 y **se descartaron a propósito**: la
ganancia es pequeña y el coste es un parámetro elegido mirando la respuesta.

Si el σ declarado se come la anomalía (`sigma_exceeds_signal`), el examen se corre con un piso
simbólico y **va a suspender**. Eso es el resultado correcto, no un error: topear σ a una
fracción del RMS observado sería mentir en la dirección peligrosa.

**Lo que este módulo NO hace, declarado:** **no discrimina entre realizaciones de ruido dentro
de un mismo régimen**, porque usa σ y no la muestra concreta. Esa mitad del hallazgo —1 de cada
3 realizaciones desvía el blanco ~170 m con diagnósticos idénticos— la cierra otra señal:
`is_floor_smear` (§8.2).

**Y sí levanta el techo, en la Fase 30 y junto a esa otra señal.** La longitud de resolución de
la banda más somera es **una de las dos pruebas** del sello de `HIGH`; la otra es el exceso de
masa de piso. Ninguna de las dos sola bastaba.

---

## 8. Diagnósticos de corrida y el veredicto reconciliado

### 8.1 Los diagnósticos R01–R06

| id | qué pregunta | dónde | criterio |
|---|---|---|---|
| **R-01** | ¿el forward del solver (padded) coincide con el del núcleo? | `_diagnosticar_r01:4221` | `‖G_pad·m_pad − G_core·m_core‖/‖G_pad·m_pad‖ < 1e-6`, si no `KERNEL_DUAL_DETECTED` |
| **R-02** | ¿cuánta masa se escapó al padding? | `_diagnosticar_r02:4287` | fracción de masa fuera del core |
| **R-03** | saturación del bound, desglosada core/padding y lower/upper | `_diagnosticar_r03:4340` | `REQUIRED` si > 10 % persiste tras corregir λ y κ |
| **R-04** | σ adaptativo | §6.2 | — |
| **R-05** | poda del dominio observable | §4.5 | — |
| **R-06** | ¿el padding saturado **cambia la física**? | `_auditar_r06_padding:4422` | contrafactual: fracción de forward / de masa / de RMS |

R-03 excluye del conteo de `sat_lower` las celdas muertas de R-05, que reciben `base_density`
**por diseño** (contraste 0) y no por saturación. Sin esa corrección el diagnóstico se inflaba
solo.

### 8.2 El veredicto reconciliado (B3)

`build_reconciled_verdict:1159`. **Un solo veredicto honesto: el eslabón más débil**
(worst-of) de todas las señales de calidad que antes convivían contradictorias en el reporte.
No inventa métrica nueva: reconcilia las que ya existen tomando la más conservadora, y luego
`apply_reconciled_verdict:1518` capa **downgrade-only** los campos individuales para que el
payload sea internamente consistente.

Señales que entran:

| señal | efecto |
|---|---|
| `confidence_level` del survey | directo |
| `model_reliability_level` | mapeado a nivel |
| `priority_class` del targeting | mapeado a nivel |
| **severidad física** del padding R-06 | `≥10 %` → LOW · `≥1 %` → MEDIUM · `<1 %` → sin efecto |
| `best_target.is_null_space_artifact` | → LOW |
| `best_target.is_floor_smear` | → LOW |
| `survey_resolution` (perfil Fase 26) | según el perfil |
| **`high_seal`** (sello de HIGH, Fase 30) | MEDIUM si NO sella; nada si sella |

Se **publican pero ya no topean**: `checkerboard_qa` (control histórico desde la Fase 26) y
`priority_class` (desde la Fase 30 — mide atractivo de *targeting*, no confiabilidad).

**Detalles que cada uno cerró un defecto real:**

- **Se ignora `delta_chi2_pct`** aunque sea el driver del gate R-06. Compara el χ² del solver
  contra un χ² recalculado con σ distinto ⇒ dispara `REMEDIATION` falsa aunque
  `mass/forward/rms ≈ 0` (medido en LdM y en un pórfido: `delta_chi2 ≈ 80-95 %` con
  `forward_frac ≈ 0`). El veredicto honesto usa lo **físico**.
- **`NOT_RUN` topea igual que `FAIL`** (Fase 21, ACAD-11). Antes sólo topaba `FAIL`, de modo que
  **el veredicto podía MEJORAR si se corrían menos diagnósticos**: el checkerboard es no-fatal,
  así que una corrida donde ese QA reventaba salía con el techo **libre** mientras la misma
  corrida con el QA sano salía capada. En un producto cuyo argumento es la honestidad, eso es
  lo único inaceptable. La decisión escogida entre las dos que el plan admitía: topear, no
  negarse a emitir veredicto — porque bloquear castigaría al usuario por un fallo del motor. El
  resultado es un veredicto **monótono**: ningún diagnóstico que se deje de correr puede subir
  el nivel.
- **`is_floor_smear`** (Fase 26). `is_null_space_artifact` exige saturación **total** al bound
  y salió `False` en **75 de 75** corridas del barrido, incluidas las 15 con PR-AUC ≤ 0,01.
  `is_floor_smear` mide la versión **continua** contra una expectativa geométrica, y es, de todo
  lo medido, **lo único que discrimina dentro de un mismo régimen**: Spearman mediano contra
  PR-AUC = **+0,83** sobre 13 regímenes, donde `chi2_red` da **0,000**.
- **El techo a `HIGH` se levantó (Fase 30) — y había TRES, no uno.** La retención declarada de
  la Fase 26 no era la que mandaba: medido sobre las 75 corridas de aquel barrido, quitarla
  sola **no cambiaba ni un veredicto**, porque `priority_class` capaba a MEDIUM **las 44 de 44**
  corridas MEDIUM — incluidas las de PR-AUC 1,000 y 11 m de error. Y detrás había un tercero:
  `priority_class` sólo llega a HIGH con `favorability.score ≥ 65`, y en la MEJOR corrida del
  barrido ese score sale **44,9 con los dos multiplicadores de calidad en 1,00** — el techo
  estaba en la aritmética de los factores. La Fase 30 retiró la retención, degradó
  `priority_class` a señal publicada (motivo semántico: atractivo ≠ confiabilidad, y ya venía
  multiplicado por la calidad, o sea contaba la calidad dos veces) y añadió el **sello**.
- **`HIGH` no se concede por AUSENCIA de defectos: hay que SELLARLO** (`_high_seal`, Fase 30).
  Hasta la Fase 29 el worst-of sólo sabía **restar**, y con el techo puesto daba igual porque
  nadie llegaba arriba. Al retirarlo se midió que no da igual: soltar `HIGH` sin criterio
  positivo declaraba HIGH a **3 corridas de 44** con **978,4 · 636,8 · 542,1 m** de error
  horizontal. El sello exige dos pruebas: (a) `shallowest_band_resolution_m <
  max_block_tested_m` — aprobar sólo el peldaño más grueso es aprobar el **suelo del examen**,
  no demostrar resolución — y (b) `floor_mass_excess ≤ 0,5`, el número que la Fase 26 midió,
  usado donde corresponde: como umbral para degradar a LOW dejaba un 12 % de margen y por eso
  sigue en 1,0, pero para **negar el nivel superior** no acusa a nadie. **La ausencia de
  cualquiera de los dos datos NO sella**: es la monotonía de la Fase 21 aplicada al nivel nuevo,
  y sin ella un reporte vacío saldría `HIGH`.
- **`ceiling` dejó de ser una constante del producto** (Fase 30). Devolvía literalmente lo mismo
  —MEDIUM, el mismo `capped_by`, el mismo párrafo— para las 75 corridas del barrido, la mejor y
  la peor: la patología del tablero un piso más arriba. Hoy nombra la prueba que **esta** corrida
  no superó, con su número, y `how_to_lift` dice qué hacer en el mundo físico.

### 8.3 Topes por preparación espacial y escala regional

`_apply_spatial_readiness_caps:118` y `services/regional_scale_preflight_service.py` topan el
veredicto cuando la georreferenciación es pobre o cuando el survey está a escala regional
(donde el producto ya midió que no funciona sin restricciones adicionales — ver
`project_terraquantum_honest_limits`).

---

## 9. La salida

### 9.1 Block model

`services/inversion_postprocess_service.py:50` construye el DataFrame Polars completo; se
persiste como **Parquet** con manifiesto y `sha256`
(`services/block_model_store.py`), y se sirve al frontend como **Apache Arrow** binario o vía
**Zarr** out-of-core para grillas > 500k celdas.

Columnas por vóxel: `ix, iy, iz, x, y, z, density, probability / relative_target_score,
sensitivity_proxy, doi_raw, posterior_std, density_zone_flag, modeled_rock_mass_tonnes,
is_active`. Las celdas de aire llevan `NaN` → `null` en JSON, con `is_active=False`.

### 9.2 La «ley» es un proxy, y el código lo grita

`estimate_grade_from_geophysics` (`inversion_postprocess_service.py:15`) es una heurística
lineal sobre `density_score`, `probability_score`, índices satelitales NIR/Fe y un
`region_factor`. **No es una ley mineral.**

El código lo marca en cuatro sitios distintos:

- `_log.warning("[WARNING] Grade heuristic used for exploration preview")` en cada llamada.
- `_GRADE_PROVENANCE = {grade_source: "heuristic_gravity_proxy", assay_supported: False,
  economically_validated: False}` adjunto a **cada vóxel**.
- `is_demo_grade: True` en cada vóxel y en el resumen.
- `expose_demo_grade=False` en el input **anula** el número (devuelve `None`) en lugar de
  emitir una cifra que se pueda citar fuera de contexto.

Los tonelajes se emiten como «masa de roca modelada derivada del modelo gravimétrico; no
representan ley mineral confirmada ni reserva». No hay cálculo de NPV/LOM en el motor: el
término aparece sólo en el copiloto de chat y en el generador de reportes, como texto.

### 9.3 Favorabilidad

`services/favorability_service.py`. Score compuesto ponderado:

```
anomaly_intensity 0,25 · depth_accessibility 0,20 · core_coherence 0,25
structural_gradient 0,15 · msx_support 0,10 · satellite_support 0,05
```

con un `DISCLAIMER` incrustado en la respuesta: «indica qué zona reúne más evidencia
geofísica independiente para priorización exploratoria. **NO** confirma presencia de mineral
económico ni depósito viable».

### 9.4 Exportadores

`services/export_service.py` (52 KB) + `services/omf_export_service.py`.

| formato | destino | notas |
|---|---|---|
| **VTR** (VTK Rectilinear) | Leapfrog Geo, Vulcan, ParaView | vía `pyevtk`; celdas de aire con `VTK_AIR_SENTINEL = −9999,0`. No-fatal si `pyevtk` falta |
| **UBC-GIF** (`.msh` + `.mod`) | MAG3D, GRAV3D, IP3D, DC3D | **un solo escritor** para las dos rutas |
| **OMF v1.0.1** | interoperabilidad Seequent | se descartó `mira-omf` por ser **LGPL** |
| **GSLIB** | geoestadística | |
| **ASEG-GDF2** | entrega **regulatoria** | |
| **CSV block model** | estándar minero | |
| **Bundle ZIP** | entregable al cliente | con manifiesto y hashes |

**Dos defectos de unidades que la Fase 22 cerró, y que eran más grandes que su ficha:**

- **ACAD-13** (`base_density` cableada a 2,6) no vivía en un escritor sino en **tres**: el
  `.vtr`, el parquet del `TargetingEngine` y el `Density_Contrast` del **ASEG-GDF2**, cuyo
  fichero de definición *declaraba por escrito* «minus 2.6 g/cm3 base». Dos de los tres viajan
  al cliente dentro del ZIP industrial. Hoy `base_density` es argumento **obligatorio** de
  `build_vtk_core_arrays` y de `export_core_to_vtr`, y el comentario del ASEG se genera con el
  valor real de la corrida.
- **ACAD-12** no era un factor 1.000: la llamada de producción tampoco pasaba `block_size`, así
  que el volumen quedaba clavado en el de una celda de 10 m en **1.034 de 2.089** corridas que
  usan otro `dx`.

**Los ejes en la exportación no son un detalle** (`export_service.py:328-380`). Ejes
TerraQuantum `(x=Este, y=prof↓, z=Norte)` contra ejes UBC `(nE, nN, nZ)` con **Z hacia
arriba**. La ruta del disco escribía `20 20 10` y la del ZIP `20 10 20` para el mismo modelo
(ACAD-1c). Hoy `tq_flat_to_ubc_flat` es el **único** reordenador, y `origin_z` es la cota del
**fondo** mientras UBC publica la del techo. El `.msh` se escribe **sin líneas de comentario**
porque `discretize.TensorMesh.read_UBC` y `np.loadtxt` no las toleran.

### 9.5 Errores accionables

`core/errors.py` (42 KB). **63 entradas** de catálogo, cada una con:

- `code` estable (`CSV_EMPTY`, `SOLVER_KERNEL_TOO_DENSE`, `GEOREF_SINGLE_ANCHOR_NO_AZIMUTH`…)
- `severity` (`error` / `warning` / `info`)
- `user_message` en **español**, descriptivo, > 100 caracteres, sin jerga cruda
- `technical_details` (dict con `cond(A)`, SNR, iteraciones, conteos…)
- `suggested_action`: pasos concretos

Familias: `CSV_*` (16), `DATA_*` (6), `GEOREF_*` (5), `SOLVER_*` (9), `BOREHOLE_*` (7),
`CORRECTION_*` (5), `MULTIMODAL_*` (2), `WARN_*` (8), `INFO_*` (2), `TQ_INTERNAL`.

El frontend consume `to_dict()` en un modal de tres pestañas RESUMEN / DETALLES / ACCIÓN; el
polling asíncrono consume `to_error_details()`.

---

## 10. Frontend: qué hace y, sobre todo, qué NO hace

Next.js 16 · React 19 · TypeScript · React-Three-Fiber / three.js · Zustand. 34.411 LOC.

- **No calcula física.** Hay un agente de revisión dedicado a esto
  (`.claude/agents/frontend-physics-boundary-reviewer`) y la regla está en `CLAUDE.md`.
- **El navegador no conoce la URL del backend.** Gate estático de CI,
  `scripts/check_client_backend_calls.mjs`, que falla si aparece
  `NEXT_PUBLIC_TERRAQUANTUM_BACKEND_URL`, `BACKEND_PUBLIC_URL` o un `http://127.0.0.1:8010`
  escrito a mano en código de cliente. Dos razones: (1) la API corre **sin autenticación** por
  defecto, y mientras todo el tráfico pase por los proxies del servidor Next, esos proxies son
  el único sitio donde añadir una cabecera el día que se active; (2) el orquestador de
  escritorio puede levantar el backend en **otro puerto** si el 8010 está ocupado, y una URL
  horneada en el bundle (Next sustituye `NEXT_PUBLIC_*` en build) apuntaría a otro proceso.
- **Los tipos del contrato se generan desde el backend.**
  `types/backend-contracts.generated.ts`: **73 tipos**, cierre transitivo de 23 contratos de
  respuesta, producidos por `python scripts/ci/generate_frontend_types.py` desde el OpenAPI de
  FastAPI. La CI corre `--check` y se pone roja si difieren. Antes había **209 tipos escritos a
  mano** copiando esquemas Pydantic; cuando el backend cambiaba un campo, no fallaba nada y el
  usuario veía un dato vacío semanas después. Un `[key: string]: unknown` en el fichero
  generado significa que el modelo Pydantic lleva `extra="allow"` — está declarado porque es
  verdad, no por comodidad.

**Render 3D** (`componentes/Scene3D.tsx`, 2.099 LOC + `lib/render/`):

- `InstancedMesh` con buffers construidos **off-thread** en un WebWorker
  (`workers/voxelBufferBuilder.worker.ts`), que devuelve `Float32Array` transferibles sin copia.
- Capa opcional de **ray-marching volumétrico** (`VolumeRaymarchLayer.tsx`), isosuperficie o
  niebla σ, con *capability gate* de GPU y `visible=false` por defecto: cablearla **no puede**
  regresionar el renderer actual. No importa `Scene3D`, ni el store, ni ningún cliente del
  backend — recibe el mismo array `cells` más accessors.
- Capas de sondajes, DOI overlay, isosuperficies, secciones, AO subsuperficie, LOD octree.
- Undo/redo por **deltas** (`store/deshacible.ts`), cerrado **por tipos** (Fase 13).

**Deuda medida y viva** (Fase 13): 44 de 93 acciones del store no tienen llamador, y `Scene3D`
lee ~19 perillas que ningún control mueve.

---

## 11. Cómo verificamos que esto está bien

Aquí está la otra mitad del producto. La tesis operativa del proyecto es: **una afirmación sin
medición no vale**, y **un gate que no se ha intentado romper no defiende nada**.

### 11.1 La jerarquía completa

```
┌─ ANTES DEL COMMIT (segundos–minutos) ────────────────────────────────
│  check.ps1        compile_check · ast_budgets · validation_inventory ·
│                   deps_closure · tsc --noEmit · eslint  [+ pytest con -Tests]
│
├─ EN CADA PUSH / PR (~1 h) ───────────────────────────────────────────
│  job backend      compile · 5 gates de arquitectura · canario de física ·
│                   pytest -m "not slow"  (2.256 de 2.290 tests)
│  job frontend     npm ci · lint · gate de llamadas directas · build
│
└─ NOCTURNO 04:30 UTC / a mano (33 min – 6,9 h medidos) ───────────────
   ingesta generativa N=5.000 · tests `validation` que nadie más corre ·
   byte-identidad de los motores (Fase 7) · byte-identidad del orquestador
   y del endpoint (Fase 8) · GATE F9 (re-invierte sobre datasets canónicos)
```

### 11.2 Marcadores de pytest

`pytest.ini`:

| marcador | significado |
|---|---|
| `unit` | rápido, sin I/O ni cómputo pesado |
| `integration` | escribe a disco (`data/projects/pytest_*`) |
| `slow` | > 10 s |
| `benchmark` | benchmark científico con **ground truth analítico**; la CI falla si las métricas de recuperación degradan |
| `validation` | **F9**: re-invierte el motor real, minutos. Se **salta** salvo `TQ_RUN_VALIDATION=1` o `--run-validation` |

El skip de `validation` se implementa en `pytest_collection_modifyitems`
(`tests/conftest.py:11`), y hay un fixture `autouse` que **resetea el rate limiter** entre
tests: el `limiter` de slowapi es un singleton de módulo que cuenta por (IP, endpoint) y
persiste dentro del mismo proceso pytest, así que sin reset varios tests contra el mismo
endpoint agotaban el presupuesto y los últimos recibían 429 — un fallo orden-dependiente que
pasa aislado y falla en suite.

### 11.3 Verdad analítica: el test que ve las regresiones de ESCALA

`tests/test_fase3_calibracion_absoluta.py`.

Existe porque se **midió** que el canario de física era ciego a media clase de errores:

| mutación | pearson_r | misfit | veredicto |
|---|---|---|---|
| ninguna (línea base) | 0,7259 | 0,654 % | PASA |
| `G = 6,6743e-11 → 7,0e-11` (+4,9 %) | 0,7259 | 0,654 % | **PASA ← ciego** |
| `W_z` apagado (exponente 0) | 0,7259 | 0,654 % | **PASA ← ciego** |
| `lambda_spatial × 500` | — | — | FALLA ← lo ve |

La razón **no** es que Pearson sea invariante al escalado: es que el propio benchmark genera el
dato sintético con la **misma constante** con la que después invierte, así que un error en `G`
se cancela exactamente. El cartel decía «ANTI-INVERSE CRIME: mallas y operadores distintos», y
es cierto para la malla, pero las **constantes** eran las mismas a ambos lados. En ese eje
seguía habiendo crimen inverso.

El test nuevo contrasta el operador forward de producción contra la **verdad analítica** —una
fórmula escrita en el propio test, independiente del motor— en el régimen donde esa verdad es
exacta: campo lejano, donde un prisma es indistinguible de una masa puntual. Cero inversión,
cero ajuste, milisegundos. `G_CODATA = 6.67430e-11` está escrito **ahí a propósito**: si
alguien toca la constante del motor, este valor no se mueve con ella y el test lo delata.

Verificado: acuerdo de **8 cifras** (ratio 1,00000000 en las cuatro geometrías). La tolerancia
de 1e-4 es ~500 veces más estrecha que la mutación de G del +4,9 % que el canario deja pasar.

### 11.4 Los gates de arquitectura

Cinco scripts en `scripts/ci/`, todos con la misma filosofía: si un criterio de aceptación no
tiene medidor, no es verificable.

**`ast_budgets.py` — presupuestos de complejidad.** Sólo biblioteca estándar (`ast`). Mide por
paquete: `loc`, `func_loc_max`, `cc_max` (McCabe práctica: +1 por `if/for/while/except/with/
assert`, por operador booleano, por comprensión y por expresión condicional) y `args_max`
(añadido por la Fase 8, cuyo criterio pedía ≤ 12 args y que **nadie medía** mientras
`invert_gravity_csv` llevaba 41 parámetros). Compara contra `ast_baseline.json` con `SLACK = 5 %`
— porque exigir «ni una línea más» convierte el gate en un obstáculo que se acaba desactivando.
Un PR que **mejore** también avisa, para que la línea base se baje a propósito.

Línea base actual:

| paquete | ficheros | LOC | func máx | CC máx | args máx |
|---|---|---|---|---|---|
| api | 22 | 6.854 | 374 | 79 | 22 |
| core | 11 | 1.881 | 67 | 19 | 7 |
| exploration | 16 | 11.693 | 812 | 116 | 39 |
| middleware | 2 | 53 | 28 | 8 | 3 |
| reporting | 2 | 1.771 | 488 | 32 | 6 |
| schemas | 11 | 3.035 | 19 | 7 | 1 |
| services | 56 | 29.632 | 777 | 181 | 36 |

(Los peores ofensores están identificados por nombre: `solve_magnetic_inversion_lsqr`
812 LOC / CC 116, `solve_inversion_lsqr` 39 args, `enrich_package_endpoint` CC 79.)

**`study_duplication.py --gate`.** Mide las ventanas de código duplicado entre los dos motores
de física y falla si suben. La Fase 7 las bajó de **192 a 20**; el criterio era < 40. El gate
existe porque el informe original citaba un `study_duplication.py` que **nunca estuvo en el
repositorio**: sin medidor, el criterio no era verificable y la duplicación podía volver sin
ruido.

**`validation_inventory.py`.** Cada script de `scripts/validation/` debe **declarar** en
`GATES.json` si es una **puerta** (decide, `exit != 0`), un **instrumento** (mide e imprime), una
**biblioteca** o una colección de **tests**. Cierra H-22: un script que mide y otro que decide se
leen igual desde fuera, y confundirlos es cómo se acaba citando un diagnóstico como si fuera un
veredicto.

**`deps_closure.py`.** Verifica que el código no importa nada que `pip install -r requirements`
no instalaría. En el runner es casi un no-op (lo instalado *es* el cierre); su trabajo lo hace
en la máquina de desarrollo, vía `check.ps1`, **antes** del push. Se añadió tras medir que
`psutil` había dejado de ser instalable —se caía de rebote con `distributed`, que la Fase 6
quitó— y que eso ponía **6 tests en rojo** en un runner limpio.

**`generate_frontend_types.py --check`.** Regenera los tipos del frontend desde el OpenAPI y
compara con lo commiteado. Va en el job de **backend** porque es ahí donde vive la app que
produce el esquema. Rojo aquí = alguien cambió un contrato y los tipos del frontend describen
un backend que ya no existe.

**`tests/test_fase5_superficie_config.py`.** Censa **por AST** las 42 variables de entorno del
backend y falla si aparece una nueva sin declarar. Destapó **5 huecos**, entre ellos que
`TQ_AUTH_ENABLED=` (vacío) **encendía** la autenticación. Va en el paso de guardas y no en el de
suite porque cuatro de sus tests llevan marca `slow` (invierten de verdad, para demostrar que
las perillas del solver no son decorativas) y `-m "not slow"` los deseleccionaría.

### 11.5 Byte-identidad: cómo se refactoriza física sin romperla

Dos arneses, y el segundo existe **porque se midió que el primero no bastaba**.

**Fase 7 — `fase7_byte_identity.py --check`.** 34 configuraciones que recorren las ramas que la
extracción compartida toca en los **dos** motores —incluidas las rutas A y B del funcional
magnético (H-33) y el solver Octree—, comparadas por **SHA-256 sobre los bits de float64**.
Criterio de aceptación de la fase: «un solo bit de diferencia ⇒ revertir». Una tolerancia
escondería justo el error que la fase podía introducir: reordenar una multiplicación cambia el
último bit, no el tercer decimal.

Por eso cada función del núcleo compartido reproduce la aritmética de sus call-sites originales
**en el mismo orden**, no una versión «equivalente». `build_model_weights` documenta el orden
exacto: `sqrt(sum(G_w²))` → `maximum(·, 1e-12)` → `1/·` para sensibilidad;
`clip(depth,1,None)` → `(·+z₀)**(0,5·β)` → `/mean` para profundidad.

**Fase 8 — `fase8_byte_identity.py --check`.** El arnés de la Fase 7 mide los **motores** y **no
defiende lo que la Fase 8 toca**: se comprobó **mutilando** `run_geophysics_inversion` y dio
**34/34 en verde**. Éste llama al servicio y al endpoint reales sobre **28 configuraciones** y
compara SHA-256 del **payload canonicalizado** y de los **bits de las columnas numéricas del
parquet** que queda en disco. Aísla el disco con `TERRAQUANTUM_DATA_DIR` y neutraliza el
enriquecimiento R3 (que sale a la red por el DEM), porque un gate de byte-identidad que depende
de internet cría lobos y acaba desactivado.

Fue este arnés —no una revisión— el que destapó que Morozov reelige λ y que el refactor lo
había perdido (§6.7).

**Resultado medible del refactor que estos arneses protegieron (Fase 8):** 2.030 → 152 LOC,
CC 183 → 12, byte-idéntico, **sin reescribir una línea**.

### 11.6 El gate F9: congelar la física validada

`scripts/validation/f9_gate_regression.py` + `f9_regression_lib.py`. **Re-invierte el motor
real** (no lee modelos cacheados) sobre los datasets canónicos, con tolerancias **explícitas y
medidas**, y emite veredicto por consola + JSON + **HTML imprimible** (material de credibilidad
para clientes).

| caso | métrica | tolerancia | medido |
|---|---|---|---|
| Esfera sintética | Pearson r | ≥ 0,70 | 0,726 |
| DO-27 (kimberlita, Canadá) | error horizontal | ≤ 70 m | ~53,7 m |
| Raglan (Ni-Cu, Quebec) | pico interior | ≤ 250 m | ~212 m |
| San Nicolás | misfit | ≤ 3 % | 1,51 % (stride 4) |
| Laguna del Maule | χ²_red | ∈ [0,7 · 1,3] | 0,987 |
| Ambigüedad-z | z-error sin restricción | **≥ 400 m** | límite conocido |

Dos cosas hacen que esto sea honesto y no decorativo:

**(1) `kind = "documented_limit"`.** El caso de ambigüedad-z pasa cuando el **límite se
reproduce**. Es decir: si la gravedad sola empezara a «resolver» la profundidad, el gate
**fallaría** — porque eso significaría que algo se rompió, no que mejoró.

**(2) `DatosNoVersionados` ≠ regresión.** DO-27 y Raglan ya estaban versionados; San Nicolás y
LdM vivían sólo bajo `data/projects/` (excluido por `.gitignore`), así que en un checkout limpio
**no existían** y el gate defendía 4 de 6 sin decirlo. Se copiaron sus observaciones —122 KB, y
un test comprueba que son **idénticas** a la corrida canónica— a `tests/fixtures/f9/`. El
resolvedor prefiere la corrida **viva** si está, para que en la máquina de desarrollo se siga
midiendo el artefacto canónico. Si no hay ninguna de las dos, se lanza `DatosNoVersionados`, que
**no** es una regresión física y el gate **no puede contarla como tal**: imprime
`NO EVALUADOS (n): …` en voz alta.

**San Nicolás usa `station_stride = 4`** y el número queda **congelado con ese submuestreo**: a
cutoff 2500 m con 1024 estaciones el kernel supera el presupuesto de memoria en máquinas de 8 GB
(el guard `SolverMemoryError` de §5.1). El ajuste sigue siendo excelente y está escrito por qué.

**Coste medido, y su consecuencia declarada**: los dos reportes guardados del propio gate dan
**1.972 s (33 min)** y **24.852 s (6,9 h)** para el **mismo veredicto PASS** — DO-27 domina y su
coste no es reproducible. Los runners de GitHub matan un job a las 6 h, así que en su régimen
lento **este job morirá por timeout**. Eso es información, no ruido: dirá que el caso caro se
salió de presupuesto. El `timeout-minutes: 330` está puesto justo por debajo.

**Prueba de sensibilidad del propio gate**: `f9_degradation_check.py` inyecta una degradación de
la física a propósito y verifica que el gate **falla**. Un gate que nunca se ha visto fallar no
se sabe si defiende.

### 11.7 La cuarta pregunta: verificación por mutación

Desde la Fase 9 hay una plantilla de gate obligatoria, y su **cuarta pregunta es «¿verificado
por mutación?»**. La práctica: se rompe el código a propósito de N formas distintas y se cuenta
cuántas ve el test. Un ejemplo real, la Fase 27: **17/17**, y para llegar ahí la propia sesión
tuvo que **cazar dos agujeros en sus propios tests**.

Es esta práctica la que produjo los hallazgos más caros del proyecto, todos del mismo tipo: **el
gate estaba en verde y no defendía nada**.

- El canario de física era ciego a `G` y a `W_z` (§11.3).
- El arnés de la Fase 7 daba 34/34 con `run_geophysics_inversion` **mutilado** (§11.5).
- El gate heredado de la Fase 19 era **decorativo**.
- El punto 1 del plan de la Fase 27 era decorativo: la ficha culpaba a un `except Exception`,
  pero `collect_submodules` **no lanza** cuando el paquete falta — devuelve `[]` con un log
  DEBUG que el `--log-level WARN` del build ni imprime. Hacer que la excepción se propagara,
  que es lo que pedía el plan, **no habría cambiado nada**. Por eso los tests comprueban el
  **resultado** de la recolección, no que se lance una excepción.

### 11.8 Reproducibilidad del build y de las dependencias

**El problema.** `requirements.txt` declara **intención** con rangos deliberados, y por eso
resolvía distinto en cada corrida: medido el 2026-09-03, hoy da `zarr 3.3.0` donde el comentario
del propio archivo anota «verificado 3.2.1». Una CI que instala versiones distintas cada noche
no puede declarar que la **física** no ha cambiado.

**La solución (Fase 27).**

- `requirements.lock`: **105 paquetes** pineados exactos con el `sha256` de **todos** los
  ficheros publicados de cada versión. La CI instala con `pip install --require-hashes`.
  Se genera con `py -3.14 scripts/ci/gen_lockfile.py`, que usa **sólo biblioteca estándar**
  (`pip-compile` habría sido una dependencia nueva). Verificado en Windows y Linux —el cierre
  resuelto es idéntico, así que no hacen falta marcadores de entorno— y con **control negativo**:
  hashes corrompidos ⇒ pip rechaza.
- `.python-version` declara el intérprete verificado (**3.14.4**), y la CI lo lee con
  `python-version-file` en vez de escribirlo a mano. Antes fijaba 3.11 y, como `zarr==3.2.1`
  exige ≥3.12, pip resolvía un **major distinto de zarr**: la CI validaba un árbol de
  dependencias que **nunca llegaba al cliente**.
- `terraquantum_backend.spec` **aborta** el build si un paquete requerido no está instalado, si
  su recolección sale **vacía**, si sale **sólo con el nombre** del paquete, o si falta el
  fichero de coeficientes IGRF-14. Medido con `omf` ausente: el `.spec` anterior empaquetaba
  `['omf']` —el nombre y **cero submódulos**, donde los sanos son 10— **sin decir nada**, y el
  instalador salía sin OMF con el build en verde. También ancla `SPECPATH` en `sys.path`: los
  **121 submódulos de la aplicación** dependían del *cwd* del build.
- `scripts/build_desktop.ps1` **resuelve** el intérprete de `.python-version` en vez de usar el
  `python` del PATH (que en la máquina de desarrollo es 3.11.9 y no tiene ninguno de los 105
  paquetes), aborta si `major.minor` no coincide, y comprueba el entorno contra el lock con
  `scripts/ci/check_env_against_lock.py` antes de empaquetar.
- `tests/test_f27_build_guards.py` (**41 tests**) es el gate, con `_FakeAnalysis` que ejecuta el
  `.spec` de verdad capturando lo que le pasa a PyInstaller.
- `tests/test_fase2_arranque.py::test_no_requirement_is_unbounded` prohíbe una dependencia nueva
  sin techo de major.

**Límite declarado**: el lock es reproducible, pero **37 de los 105** paquetes están instalados
en la máquina de desarrollo en otra versión. El núcleo numérico
(`numpy`/`scipy`/`pyproj`/`polars`) sí coincide exacto y un test lo vigila, así que la física no
se mueve; reconciliar el resto exige instalar dependencias. Por eso el comprobador trata la
**ausencia** como fatal y la **deriva dentro de rango** como aviso.

### 11.9 Otros gates y arneses

| gate | qué prueba |
|---|---|
| `f2b_gate_cabinet.py` | el gabinete del consultor de punta a punta, con datos reales |
| `f3_gate_joint96k.py` | el caso que mató al proxy: joint ~96k vóxeles E2E |
| `f6_gate_copilot.py` | 20 preguntas de consultor ancladas a una corrida **real** (el copiloto no puede alucinar números) |
| `f7_gate_packaging.py` | empaque local-first + licencias |
| `f8_gate_storm.py` | tormenta transversal sobre el producto entero |
| `test_ingesta_generativa.py` | **generativo**: 400 casos por defecto, **5.000** en el nocturno (`TQ_GEN_N`) |
| `test_ingesta_never_crashes.py` | la ingesta nunca revienta, pase lo que pase |
| `test_corpus_csv_reales.py` | CSVs **sucios reales**, no limpios — la lección del blindaje de 7 pilares |
| `test_benchmark_checkerboard/dipping_dike/two_body` | benchmarks con ground truth |
| `test_analytic_sphere_validation.py`, `test_sphere_forward.py` | verdad analítica |
| `test_simpeg_comparison.py` | contraste contra SimPEG |
| `test_no_noise_injection.py` | el motor **no** modifica las observaciones |
| `test_grade_integrity.py` | la ley proxy no se puede citar como ley |
| `e2e/` (Playwright) | flujo de usuario en el navegador |

### 11.10 Observabilidad de la corrida

- **Logging estructurado** (`structlog`), con un test que prohíbe escribir a stdout desde el
  motor (`test_fase0_logger_no_stdout.py`).
- **Diario `boot.jsonl`** (idea reutilizable de la Fase 2): el arranque del escritorio deja
  trazas que permiten diagnosticar un fallo de instalación sin acceso a la máquina.
- **`/diagnostics/manifest`**: exportar un diagnóstico **sin datos del cliente**.
- **Snapshots por corrida**: `inputs.json`, `observations.json`, `report.json`,
  `schedule.json`, manifiesto con `sha256` — es lo que permite que F9 re-invierta exactamente lo
  mismo meses después.
- Prometheus + OpenTelemetry opcionales (`OTEL_ENABLED=false` por defecto → cero overhead).

### 11.11 Ejecución asíncrona y cancelación

`services/run_queue_service.py`. El problema que mataba al producto: `/v2/load-package` era
**síncrono**, y una inversión joint de 96k vóxeles (20+ min) reventaba el proxy («error interno
del proxy») dejando al usuario sin feedback.

Diseño, con cero infraestructura nueva (nada de Redis ni Celery, que un local-first no debe
pedir):

- Worker = `multiprocessing.Process` (spawn) por corrida, máximo `TQ_INVERSION_WORKERS`
  (por defecto 1) simultáneos, cola FIFO en memoria. Es CPU-bound: el GIL castiga a los hilos, y
  un proceso aparte además permite **cancelar de verdad** (`terminate`) sin tocar el motor
  físico validado. Se usa `Process` directo y no `ProcessPoolExecutor` porque el pool **no
  permite cancelar un trabajo en curso**.
- El hijo importa `services.run_queue_service`, no `main.py`, para que el bootstrap de spawn
  cargue lo mínimo.
- Cancelación en dos capas: fichero cooperativo `cancel.requested` en el directorio de la
  corrida + `terminate()` como garantía.
- Un watcher en el padre libera el slot, lanza el siguiente y marca «interrumpida» si el hijo
  murió sin despedirse.
- **Presupuesto de vóxeles**: antes de encolar se estima el tiempo por (ruta, nº de vóxeles) con
  coeficientes **medidos**, y se avisa si excede el umbral. Nunca más un joint de 96k vóxeles
  sorpresa.

---

## 12. Límites medidos: lo que este sistema NO puede afirmar

Esta lista no es modestia: cada línea es un experimento con número, y varias están congeladas
como tests para que no se olviden.

1. **La gravedad sola no resuelve la profundidad.** Sintético de ambigüedad-z: z-error robusto de
   **2.675 m**. El ancla de sondaje es **tautológica** — fija sus propias celdas; el error
   *off-anchor* sigue en **325 m**.
2. **El smear profundo es null-space consistente con el dato.** Cuatro hipótesis del *sink* de
   Laguna del Maule están **muertas** (malla/bounds, ancla, regional, λ). El cuerpo somero es
   robusto hasta ~1,6 km.
3. **La palanca de profundidad es la MAGNITUD de λ**, no `depth_beta`. Y la fragilidad de Morozov
   en profundo **es** el null-space: `χ²(λ)` se aplana (4,06 → 1,27 → 0,56). Rescata el régimen
   moderado (150–300 m), no el profundo.
4. **`HIGH` ya es alcanzable (Fase 30), y hay que SELLARLO.** No se concede por ausencia de
   defectos: exige resolución por debajo del peldaño más grueso del examen y `floor_mass_excess
   ≤ 0,5`. El techo anterior eran **tres** cosas, no una, y la única declarada no era la que
   mandaba — ver `validation/HALLAZGO_2026-09-06_techo_high.md`.
5. **Bimodalidad no resuelta.** 1 de cada 3 realizaciones de ruido da **169 m** en vez de 19 m
   con diagnósticos **idénticos**. `is_floor_smear` es la única señal que discrimina dentro de un
   régimen (ρ = +0,83), y el perfil de resolución **no** cierra esta mitad porque usa σ, no la
   muestra.
6. **Depósitos pequeños sí; regional (tipo Bushveld) no** sin restricciones adicionales.
7. **El producto es targeting/estructura, no estimación de recursos.** El leave-one-out dio
   **NO_GO medido**: densidad o ley entre pozos es kriging, y nadie lo hace con gravedad.
8. **Las validaciones externas validan el MOTOR, no competitividad frente a VOXI.** «El motor
   funciona» ≠ «el producto es confiable».
9. **`WARNING` en el checkerboard sigue permitiendo `HIGH`** (deuda abierta de la Fase 21).
10. **Deuda sin dueño registrada**: H-34, las ~19 perillas huérfanas de `Scene3D`, H-F11-2/3, el
    residuo del 48 % en la corrección de terreno, y `MagnetizationVectors.tsx:99`, que sigue
    dibujando a `90−D`.
11. **Presupuestos AST altos y declarados**: `solve_magnetic_inversion_lsqr` (812 LOC, CC 116) y
    `solve_inversion_lsqr` (39 args) siguen siendo los peores ofensores. El gate impide que
    **empeoren**; no pretende que estén bien.

---

## 13. Índice rápido de ficheros clave

| Quiero entender… | Abrir |
|---|---|
| El kernel gravimétrico (Nagy + masa puntual) | `exploration/gravimetry.py:704-1155` |
| El sistema aumentado que se resuelve | `exploration/gravimetry.py:2338-2515` |
| El despacho real del solver | `exploration/gravimetry.py:2515-2650` |
| El bucle IRLS compacto | `exploration/gravimetry.py:2650-2854` |
| El peso de modelo (y por qué β estaba inerte) | `exploration/potential_field_core.py:248-400` |
| La declaración del funcional por corrida | `exploration/potential_field_core.py:404-540` |
| El kernel magnético (dipolo, prisma, MVI, FTG) | `exploration/magnetometry.py:125-730` |
| Cross-gradient, Gramian, PGI 2D | `services/joint_inversion.py:82-300` |
| Las correcciones de gabinete | `services/gravity_corrections_service.py` |
| La orquestación de una corrida gravimétrica | `services/geophysics_service.py:3311-5822` |
| El veredicto reconciliado | `services/geophysics_service.py:1159-1548` |
| El perfil de resolución | `services/resolution_qa.py` |
| La malla con padding | `services/inversion_kernel_service.py:57-160` |
| El catálogo de errores | `core/errors.py` |
| La superficie de configuración | `core/config.py` |
| El gate de física congelada | `scripts/validation/f9_regression_lib.py` |
| Los gates de arquitectura | `scripts/ci/` |
| Qué corre y cuándo | `.github/workflows/ci.yml` |
| El check pre-commit | `check.ps1` |

---

## 14. Cierre

La arquitectura de este sistema tiene dos mitades que pesan lo mismo.

La primera es la **física**: un operador forward exacto en campo cercano y barato en campo
lejano, un problema inverso de Tikhonov con pesos deliberados, y un catálogo de restricciones
(sondajes, litología, petrofísica, estructura, geología implícita) que entran todas por el mismo
hook algebraico.

La segunda es el **sistema que impide que la primera mienta**. Y esa mitad no se construyó por
gusto: se construyó porque cada vez que se midió un gate en verde, se encontró que defendía menos
de lo que decía. El canario era ciego a la escala. El arnés de byte-identidad daba 34/34 con el
orquestador mutilado. El escáner de λ prometía un χ² que el solver fallaba por **12.700×**. El
reporte afirmaba `bounded_solver_active: true` mientras despachaba `LSQR+clip`. El veredicto
**mejoraba si se corrían menos diagnósticos**. El examen de resolución era imposible de aprobar
por tres razones independientes, y calificaba a otro solver.

Ninguno de esos se encontró leyendo. Se encontraron **midiendo**, y casi siempre con la misma
pregunta: *si rompo esto a propósito, ¿alguien se entera?*

Ésa es la pregunta que define el rigor de este proyecto, y es la que hay que seguir haciendo.
