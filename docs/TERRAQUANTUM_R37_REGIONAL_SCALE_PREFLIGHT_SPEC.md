# TERRAQUANTUM R3.7-A — Regional Scale Preflight Specification

**Versión:** 1.0  
**Fecha:** 2026-05-22  
**Estado:** SPEC (doc-only — sin cambios de código productivo)  
**Prerequisito:** R3.5 Industrial Input Contract cerrado funcionalmente  
**Siguiente fase de implementación:** R3.7-B

---

## 1. Resumen Ejecutivo

TerraQuantum ya acepta datasets de gravedad reales, incluyendo datos públicos NOAA de escala continental. Esta capacidad expone un problema de clasificación de escala: el sistema no distingue entre un survey minero local (apto para inversión 3D única) y un dataset regional (apto para análisis general, pero que requiere subset/tile antes de invertir).

El resultado actual es un HTTP 422 genérico cuando el auto-grid genera nx o nz superiores al límite del schema de inversión (`<=80`). Este error no es una falla de datos; es una decisión de escala. El dataset NOAA Andes B1 (6.151 estaciones, escala continental) es un ejemplo concreto y reproducible.

El presente documento especifica el **Regional Scale Preflight**: un módulo de clasificación que se calculará en `/preview` y en `/invert`, expuesto en metadata, UI y reporte, con el objetivo de:

1. Detectar la clase de escala antes de intentar la inversión.
2. Comunicar al usuario en lenguaje técnico honesto por qué no puede correr inversión única en un dataset regional.
3. Sugerir acciones concretas: subset, tile, parámetros explícitos.
4. No bloquear el sistema para datos locales válidos que hoy ya funcionan.

---

## 2. Evidencia desde Benchmark NOAA Andes B1

Fuente: `benchmarks/public_gravity_b1/README.md` y `benchmarks/public_gravity_b1/qa_notes.md`

| Prueba | Resultado |
|---|---|
| Dataset | South America / Andes Gravity Station Data 1997, NOAA/NCEI |
| Archivo full | `benchmarks/public_gravity_b1/terraquantum_ready.csv` |
| Estaciones full | 6.151 |
| Preview full | HTTP 200 — status: ok — spatial_readiness: PROFESSIONAL_SURVEY |
| Inversion full | HTTP 422 — nx=97, nz=145 — schema cap <=80 excedido |
| Bloqueador | Scale-contract limit, no falla de datos |
| Archivo subset | `benchmarks/public_gravity_b1/normalized/andes97_invert_subset.csv` |
| Estaciones subset | 152 — ventana `-25.8 <= lat <= -25.0`, `-70.2 <= lon <= -69.2` |
| Preview subset | nx=27, ny=16, nz=24, voxel_count=10.368 |
| Inversion subset | HTTP 200 — status: done — R3 enrichment: ok |
| `/block-model` subset | has_elevation_data=true |
| Reporte subset | HTML contiene Contrato Espacial de Entrada |

### 2.1 Problema de Profundidad en el Subset

Aunque el subset pasa la inversión, la profundidad estimada es problemática:

- Extensión del subset: ~88 km N-S × ~100 km E-W (coordenadas geográficas a ~25°S)
- Fórmula en `services/grid_calculator_service.py:127`:
  ```python
  depth_m = clamp(max_extent * 0.6, MIN_DEPTH_M, MAX_DEPTH_M)
  # MIN_DEPTH_M = 1000, MAX_DEPTH_M = 100000
  ```
- Para max_extent ≈ 100 km → `depth_m = clamp(100000 * 0.6, 1000, 100000) = 60000 m = 60 km`
- Una profundidad de inversión de 60 km es geológicamente válida para estudios de corteza, pero no es razonable como modelo de bloque minero local (rango típico: 0.5–3 km).

Este comportamiento es correcto para la fórmula, pero el sistema no lo comunica. El usuario ve un modelo aparentemente exitoso cuya profundidad no corresponde a ninguna escala minera.

---

## 3. Problema Actual

### 3.1 UX

- `/invert` con dataset regional devuelve HTTP 422 con el body de Pydantic ValidationError.
- El mensaje expone `"nx": Value should be less than or equal to 80` sin contexto de escala.
- No hay sugerencia de subset ni tile.
- No hay distinción entre "dataset inválido" y "dataset demasiado grande para inversión única".
- El frontend muestra el error crudo sin interpretación.

Archivo relevante: `terraquantum-backend/api/gravity_import_api.py:780-787` — bloque `except ValidationError`.

### 3.2 Backend — Auto-Grid Detecta Tarde

El auto-grid (`services/grid_calculator_service.py:compute_auto_grid`) respeta el límite de voxels totales (R-10: nx×ny×nz ≤ 200.000) pero **no valida** el límite por dimensión (≤80). Este límite existe solo en el schema Pydantic de inversión (`schemas/geophysics_schema.py:21-23`).

El flujo actual:

```
import_gravity_csv_v1  →  compute_auto_grid  →  (nx=97, nz=145, ≤200k OK)
→  GeophysicsInvertInput(nx=97)  →  ValidationError  →  HTTP 422 genérico
```

No hay punto de intercepción temprana que etiquete el dataset como REGIONAL_SCALE antes del intento de inversión.

### 3.3 Modelo — Depth Escala con Área Horizontal

La fórmula `depth_m = clamp(max_extent * 0.6, 1000, 100000)` en `grid_calculator_service.py:127` vincula la profundidad del modelo con la extensión horizontal máxima. Esta relación es razonable para surveys locales (ej. 5 km → depth = 3 km), pero genera profundidades absurdas para surveys regionales (ej. 100 km → depth = 60 km).

No existe actualmente ningún mecanismo que advierta cuando la profundidad estimada excede un umbral razonable para un contexto minero.

### 3.4 Visual

Si un dataset regional pasara la inversión (por ejemplo con parámetros explícitos o un subset accidental que cumple los límites), el modelo 3D tendría voxeles de varios km de lado. El viewer en `Exploration3DView.tsx` y `Scene3D` renderizan lo que reciben. No hay ninguna advertencia visual de que la escala del modelo no corresponde a contexto minero.

### 3.5 Producto

Una empresa minera que carga datos NOAA reales como prueba del sistema recibe un error 422 sin explicación. Necesita una respuesta que diga: "Este dataset es regional, no es inválido, y estas son las opciones para trabajar con él."

---

## 4. Definiciones de Escala

Las siguientes categorías son propuestas iniciales conservadoras. **Los umbrales numéricos no son dogma**; deben calibrarse con casos reales en R3.7-G.

### 4.1 `LOCAL_SURVEY`

| Parámetro | Valor orientativo |
|---|---|
| extent_x_m | ≤ 10.000 m |
| extent_z_m | ≤ 10.000 m |
| area_km2 | ≤ 100 km² |
| station_count | cualquiera ≥ 10 |
| depth_m estimado | ≤ 6.000 m (60% de 10 km) |
| nx, nz estimados | probablemente ≤ 40 |
| Inversión única | Permitida sin advertencia de escala |
| Uso típico | Survey de detalle minero, exploración local |

### 4.2 `DISTRICT_SCALE`

| Parámetro | Valor orientativo |
|---|---|
| extent_x_m | 10.000 – 30.000 m |
| extent_z_m | 10.000 – 30.000 m |
| area_km2 | 100 – 900 km² |
| depth_m estimado | 6.000 – 18.000 m |
| nx, nz estimados | posiblemente 30–80 |
| Inversión única | Permitida con advertencia de escala y sugerencia de parámetros explícitos |
| Uso típico | Distrito minero, exploración de camp |

### 4.3 `REGIONAL_SCALE`

| Parámetro | Valor orientativo |
|---|---|
| extent_x_m | 30.000 – 100.000 m |
| extent_z_m | 30.000 – 100.000 m |
| area_km2 | 900 – 10.000 km² |
| depth_m estimado | 18.000 – 60.000 m |
| nx, nz estimados | 50–80 (dependiendo del block_size) |
| Inversión única | No recomendada como modelo minero único |
| Acción sugerida | Subset por ventana de interés o parámetros explícitos con block_size grande |
| Ejemplo | Andes B1 subset (152 estaciones, ~88 km × 100 km) |

### 4.4 `TOO_LARGE_SINGLE_INVERSION`

| Parámetro | Valor orientativo |
|---|---|
| extent_x_m | > 100.000 m (o cualquier extensión que genere nx > 80 o nz > 80) |
| extent_z_m | > 100.000 m |
| area_km2 | > 10.000 km² |
| depth_m estimado | > 60.000 m |
| nx o nz estimados | > 80 |
| Inversión única | Bloqueada — auto-grid excede schema <=80 por dimensión |
| Acción obligatoria | Tile / subset / parámetros explícitos muy grandes |
| Ejemplo | Andes B1 full (6.151 estaciones, nx=97, nz=145) |

### 4.5 Lógica de Clasificación Propuesta

```python
# Pseudocódigo — no código productivo
def classify_scale(estimated_nx, estimated_nz, extent_x_m, extent_z_m, area_km2):
    max_extent = max(extent_x_m, extent_z_m)
    if estimated_nx > MAX_NX_SCHEMA or estimated_nz > MAX_NZ_SCHEMA:
        return "TOO_LARGE_SINGLE_INVERSION"
    if max_extent > 100_000 or area_km2 > 10_000:
        return "REGIONAL_SCALE"
    if max_extent > 30_000 or area_km2 > 900:
        return "DISTRICT_SCALE"
    return "LOCAL_SURVEY"

# MAX_NX_SCHEMA = MAX_NY_SCHEMA = MAX_NZ_SCHEMA = 80
# Definidos en schemas/geophysics_schema.py:21-23
```

La clasificación debe usar **los mismos valores de nx/nz producidos por `compute_auto_grid`**, sin recalcular. Esos valores ya existen en `AutoGrid.nx`, `AutoGrid.nz` devueltos por `services/grid_calculator_service.py:compute_auto_grid`.

---

## 5. Schema Propuesto: RegionalScalePreflight

Pydantic schema futuro — ubicación sugerida: `schemas/gravity_import_schema.py`, sección nueva al final.

```python
# FUTURO — no implementar todavía
class RegionalScalePreflight(BaseModel):
    version: str = "regional_scale_preflight_v0_1"

    # Clasificación
    scale_class: str
    # Valores: "LOCAL_SURVEY" | "DISTRICT_SCALE" | "REGIONAL_SCALE" | "TOO_LARGE_SINGLE_INVERSION"

    can_run_single_inversion: bool
    requires_user_acknowledgement: bool
    recommended_action: str

    # Dimensiones del dataset
    extent_x_m: float
    extent_z_m: float
    area_km2: float
    station_count: int

    # Grilla estimada (derivada del auto_grid actual)
    estimated_nx: int
    estimated_ny: int
    estimated_nz: int
    estimated_voxel_count: int
    estimated_depth_m: float
    estimated_block_size_m: float

    # Límites del schema de inversión
    max_allowed_nx: int   # = 80
    max_allowed_ny: int   # = 80
    max_allowed_nz: int   # = 80
    max_allowed_voxel_count: int  # = 200000 (R-10 limit)

    # Razones y advertencias
    warnings: List[str]
    blocked_reasons: List[str]
    allowed_outputs: List[str]

    # Sugerencias de acción
    suggested_tile_size_m: Optional[float]
    suggested_subset_bbox: Optional[dict]  # {lat_min, lat_max, lon_min, lon_max}

    # Trazabilidad
    rationale: List[str]
```

### 5.1 Campos Derivables Hoy

Los siguientes campos del `RegionalScalePreflight` son derivables sin trabajo adicional porque ya existen en el pipeline:

| Campo preflight | Fuente actual |
|---|---|
| `extent_x_m` | `coordinate_transform.x_extent_m` (`schemas/gravity_import_schema.py:75`) |
| `extent_z_m` | `coordinate_transform.z_extent_m` (`schemas/gravity_import_schema.py:76`) |
| `area_km2` | `csv_analysis.sampling.area_km2` (`schemas/gravity_import_schema.py:19`) |
| `station_count` | `csv_analysis.observation_count` |
| `estimated_nx` | `auto_grid.nx` |
| `estimated_ny` | `auto_grid.ny` |
| `estimated_nz` | `auto_grid.nz` |
| `estimated_voxel_count` | `auto_grid.voxel_count` |
| `estimated_depth_m` | `auto_grid.depth_m` |
| `estimated_block_size_m` | `auto_grid.block_size_m` |
| `max_allowed_nx/ny/nz` | Constante `80` de `schemas/geophysics_schema.py:21-23` |
| `max_allowed_voxel_count` | Constante `R10_LIMIT = 200000` de `services/grid_calculator_service.py:7` |

La lógica de clasificación será nueva, pero todos sus insumos ya existen.

---

## 6. Dónde Calcularlo

### 6.1 En `/preview` (nuevo — R3.7-B)

El endpoint `POST /gravity-import/preview` en `api/gravity_import_api.py:530` ya calcula `auto_grid` y lo devuelve en la respuesta.

**Propuesta:** Después de calcular `auto_grid`, calcular `regional_scale_preflight` e incluirlo en la respuesta JSON del preview bajo la clave `"regional_scale_preflight"`.

El preflight en preview **no bloquea**. Solo informa. El usuario puede ver la clasificación antes de intentar invertir.

### 6.2 En `/invert` (nuevo gate — R3.7-C)

El endpoint `POST /gravity-import/invert` en `api/gravity_import_api.py:614` ya calcula `auto_grid` en `import_gravity_csv_v1`. Antes de construir `GeophysicsInvertInput`, calcular el preflight y aplicar la regla de bloqueo.

El bloqueo ocurre **después** del spatial readiness gate (`_enforce_spatial_readiness_gate`) y **antes** de la construcción de `GeophysicsInvertInput`.

Si `scale_class == "TOO_LARGE_SINGLE_INVERSION"`, lanzar HTTP 422 estructurado (ver §8) en lugar de dejar que Pydantic ValidationError propague el error crudo.

### 6.3 Persistencia

| Archivo | Campo a agregar |
|---|---|
| `gravity_import_metadata.json` | `"regional_scale_preflight": {...}` |
| `project_meta.json` | `"regional_scale_preflight": {...}` |
| `/export-report` response | `"regional_scale_preflight": {...}` en el body |
| Reporte HTML | Sección "Regional Scale Preflight" (ver §10) |

El proyecto ya persiste `spatial_readiness` en ambos JSON (`api/gravity_import_api.py:962, 1002`). El preflight sigue el mismo patrón.

---

## 7. Reglas de Bloqueo

### 7.1 Bloqueo Incondicional

Si `estimated_nx > 80 OR estimated_nz > 80 OR estimated_ny > 80`:
- `scale_class = "TOO_LARGE_SINGLE_INVERSION"`
- `can_run_single_inversion = False`
- Lanzar HTTP 422 estructurado
- No hay acknowledgement que desbloquee este caso

Justificación: el schema `GeophysicsInvertInput` rechazará el input de todas formas. El preflight solo anticipa ese rechazo con un mensaje útil.

### 7.2 Advertencia con Acknowledgement

Si `scale_class == "REGIONAL_SCALE"` y `estimated_depth_m > DEPTH_MINING_THRESHOLD`:
- `requires_user_acknowledgement = True`
- `required_acknowledgement = "ACK_REGIONAL_SCALE_DEPTH_CONTEXT"`
- Advertir que la profundidad del modelo no corresponde a escala minera local
- Permitir inversión con acknowledgement (la grilla cabe en <=80)

`DEPTH_MINING_THRESHOLD`: valor inicial propuesto `6000 m`. Calibrar en R3.7-G.

### 7.3 Advertencia Simple

Si `scale_class == "DISTRICT_SCALE"` con `estimated_depth_m > 6000 m`:
- Agregar warning de profundidad
- No bloquear, no exigir acknowledgement

### 7.4 Caso de Forzado Regional

Si el usuario fuerza con acknowledgement regional:
- Permitir solo si `estimated_nx <= 80 AND estimated_ny <= 80 AND estimated_nz <= 80`
- No permitir si `scale_class == "TOO_LARGE_SINGLE_INVERSION"` (ese bloqueo es incondicional)

---

## 8. Formato Nuevo de Error HTTP 422

Cuando el preflight bloquea la inversión, reemplazar el error Pydantic genérico por:

```json
{
  "error": "REGIONAL_SCALE_PREFLIGHT",
  "scale_class": "TOO_LARGE_SINGLE_INVERSION",
  "message": "El dataset cubre una escala regional y genera una grilla mayor al límite de inversión única. Use un recorte/subset, tileado regional o parámetros explícitos.",
  "recommended_action": "Seleccionar una ventana de hasta ~10.000 m × 10.000 m para una primera inversión local.",
  "extent_x_m": 874230.5,
  "extent_z_m": 1052800.0,
  "area_km2": 920000.0,
  "estimated_grid": {
    "nx": 97,
    "ny": 13,
    "nz": 145,
    "block_size_m": 9014,
    "depth_m": 100000.0,
    "voxel_count": 182949
  },
  "limits": {
    "max_nx": 80,
    "max_ny": 80,
    "max_nz": 80,
    "max_voxel_count": 200000
  },
  "suggestions": [
    "Exportar un subset con ventana lat/lon de interés (ej: área de ~1° × 1°).",
    "Usar el helper de subset/tile (disponible en R3.7-F).",
    "Declarar block_size_m explícito >= 14.000 m para forzar nx/nz dentro del límite — no recomendado para contexto minero local."
  ]
}
```

### 8.1 Mensaje para `terraquantum_ready.csv`

```
"El dataset cubre una escala regional (escala Andes, ~874 km × ~1.053 km) y genera
una grilla de nx=97, nz=145, que excede el límite de inversión única (<=80 por dimensión).
El dataset no es inválido. Para inversión minera local, seleccionar una subventana
geográfica de interés y exportar un subset CSV. La inversión sobre el subset es válida
como se demostró con andes97_invert_subset.csv (152 estaciones, nx=27, nz=24)."
```

---

## 9. UI Requerida

### 9.1 GravityCsvPreviewPanel — Nuevo Bloque "Escala del Dataset"

Archivo: `terraquantum-web/componentes/GravityCsvPreviewPanel.tsx`

El panel ya muestra `spatial_readiness` con badge de colores (`getSpatialReadinessColors`, línea ~62-71). Se propone agregar un bloque análogo para `regional_scale_preflight`.

**Contenido requerido del bloque:**

```
┌─ Escala del Dataset ─────────────────────────────────────────────────────┐
│  Clase: [ DISTRICT_SCALE ] (badge color: amarillo)                       │
│  Extensión: 25.3 km × 18.7 km                                            │
│  Área: 473 km²                                                            │
│  Grilla estimada: nx=38, ny=12, nz=28 — voxels: 12.768                  │
│  Profundidad estimada: 15.2 km                                            │
│  ⚠ La profundidad estimada supera el rango típico de modelo minero local │
│  Inversión única: [ Permitida con advertencia ]                           │
│  Acción recomendada: Parámetros explícitos o reducir área de interés     │
└──────────────────────────────────────────────────────────────────────────┘
```

Para `TOO_LARGE_SINGLE_INVERSION`:
```
┌─ Escala del Dataset ─────────────────────────────────────────────────────┐
│  Clase: [ TOO_LARGE — ESCALA REGIONAL ] (badge color: rojo)              │
│  Extensión: 874 km × 1.053 km                                            │
│  Grilla estimada: nx=97, nz=145 — EXCEDE LÍMITE (máx 80 por dimensión)  │
│  Inversión única: [ BLOQUEADA ]                                           │
│  Acción requerida: Seleccionar subset / tile de la región de interés     │
│  [ Ver sugerencia de subset ] [ Exportar subset CSV ]                    │
└──────────────────────────────────────────────────────────────────────────┘
```

### 9.2 Botón "Invertir"

- `scale_class == "LOCAL_SURVEY"` → botón habilitado, sin cambios
- `scale_class == "DISTRICT_SCALE"` → botón habilitado, tooltip de advertencia de profundidad
- `scale_class == "REGIONAL_SCALE"` → botón habilitado si nx/nz ≤ 80, con checkbox de acknowledgement
- `scale_class == "TOO_LARGE_SINGLE_INVERSION"` → botón deshabilitado con tooltip: "Dataset regional — se requiere subset"

### 9.3 Colores Propuestos

| scale_class | Color |
|---|---|
| LOCAL_SURVEY | Verde |
| DISTRICT_SCALE | Amarillo |
| REGIONAL_SCALE | Naranja |
| TOO_LARGE_SINGLE_INVERSION | Rojo |

Seguir la convención existente del panel: `text-green-400`, `text-yellow-400`, `text-orange-400`, `text-red-400`.

---

## 10. Reporte HTML Requerido

El reporte HTML generado por `/export-report` debe incluir una sección **"Regional Scale Preflight"** con:

```markdown
## Escala del Dataset y Viabilidad de Inversión

| Campo | Valor |
|---|---|
| Clase de escala | DISTRICT_SCALE |
| Extensión horizontal | 25 km × 19 km |
| Área | 473 km² |
| Profundidad de modelo estimada | 15.2 km |
| Inversión única permitida | Sí (con advertencia de escala) |
| Grilla estimada | nx=38, ny=12, nz=28 |

**Resultado:** La inversión fue ejecutada. La profundidad del modelo (15.2 km) supera
el rango típico de un modelo de bloque minero local. Este parámetro es generado
automáticamente; en un contexto minero real debe ser revisado y ajustado por el
geofísico responsable.

**Limitaciones:**
- Este análisis clasifica la escala del dataset, no la validez geológica.
- No certifica ni refuta la presencia de mineralización.
- No reemplaza la interpretación profesional del modelo de densidades.
```

---

## 11. Tiling / Subset Futuro (R3.7-F)

Este documento define la necesidad pero no implementa el tileado. R3.7-F debe implementar:

- Selección de bbox interactiva en el mapa del `GravityCsvPreviewPanel` o un helper UI independiente.
- Filtrado del CSV por ventana geográfica (lat/lon o UTM) → nuevo CSV descargable.
- Capacidad de correr múltiples tiles y comparar resultados (R3.7-F o R4+).
- Exportación del subset resultante como CSV compatible con TerraQuantum Gravity CSV v1.

El endpoint `POST /gravity-import/preview` ya puede usarse para estimar la grilla de cualquier subset antes de invertir; no se requiere nuevo endpoint para el subset helper.

**No implementar tileado en R3.7-B ni R3.7-C.** Primero resolver la detección y el mensaje.

---

## 12. Relación con R4 Visual

R4 no debe intentar "arreglar visualmente" un modelo con escala incorrecta.

El `Exploration3DView.tsx` y `Scene3D` deben recibir del preflight:

| Campo | Uso en R4 |
|---|---|
| `scale_class` | Mostrar badge de escala en el viewer 3D |
| `estimated_depth_m` | Informar al usuario la profundidad real del modelo antes de explorar |
| `extent_x_m`, `extent_z_m` | Escalar los ejes del viewer correctamente |
| `can_run_single_inversion` | Deshabilitar opciones de análisis minero si clase es regional |

R4 no debe escalar ni normalizar el modelo para que "se vea bien". Si el modelo es de 60 km de profundidad, eso debe ser visible y comunicado como contexto regional, no transformado a escala local.

El campo `visualMode` ya existe en el frontend (`GravityCsvPreviewPanel.tsx:80`: `type BackendVoxelModel = VoxelMineralModel & { visualMode?: string }`). R4 puede usar `visualMode: "regional_context"` para activar un renderizado diferenciado.

---

## 13. Fases Propuestas

### R3.7-A (este documento)
**Especificación técnica únicamente.** Sin cambios de código productivo.

### R3.7-B — Backend Preflight Schema + Preview
- Implementar `RegionalScalePreflight` en `schemas/gravity_import_schema.py`
- Implementar función de clasificación en `services/grid_calculator_service.py` o nuevo `services/regional_scale_service.py`
- Calcular preflight en `/preview` y devolverlo en la respuesta JSON
- Escribir test con dataset sintético representativo de cada categoría de escala
- **Scope**: solo backend, solo preview — NO tocar `/invert` todavía

### R3.7-C — Hard Gate Regional en `/invert`
- En `api/gravity_import_api.py:/invert`, agregar bloqueo de escala antes de `GeophysicsInvertInput`
- Lanzar HTTP 422 estructurado (§8) en lugar de dejar propagar ValidationError
- Manejar el caso `acknowledge_spatial_risk` para REGIONAL_SCALE con nx/nz válidos
- **Scope**: solo backend, solo `/invert`

### R3.7-D — UI: Mensajes y Botón Bloqueado
- Agregar bloque "Escala del Dataset" en `GravityCsvPreviewPanel.tsx`
- Consumir `regional_scale_preflight` de la respuesta `/preview`
- Deshabilitar botón de inversión si `TOO_LARGE_SINGLE_INVERSION`
- Mostrar mensaje de advertencia para `REGIONAL_SCALE` y `DISTRICT_SCALE`
- **Scope**: solo frontend, solo GravityCsvPreviewPanel

### R3.7-E — Reporte HTML
- Agregar sección "Regional Scale Preflight" al reporte HTML de `/export-report`
- Incluir los campos del preflight en `report.json`
- **Scope**: solo reporte, no tocar solver ni viewer 3D

### R3.7-F — Subset / Tile Helper Básico
- UI de selección de bbox (lat/lon slider o inputs directos)
- Filtrado CSV en backend por ventana geográfica
- Descarga del subset como CSV válido
- **Scope**: nuevo endpoint ligero + UI mínima

### R3.7-G — QA con NOAA Andes
- Test automatizado con `terraquantum_ready.csv` → esperado: `TOO_LARGE_SINGLE_INVERSION` + HTTP 422 estructurado, no Pydantic error
- Test con `andes97_invert_subset.csv` → esperado: `REGIONAL_SCALE` + warning de profundidad + inversión exitosa
- Calibrar umbrales de escala según resultados reales
- **Scope**: solo benchmarks/scripts de validación

---

## 14. Criterios de Aceptación

- [ ] `terraquantum_ready.csv` (6.151 estaciones, full) no muestra `"nx": Value should be less than or equal to 80` — muestra error estructurado `REGIONAL_SCALE_PREFLIGHT`
- [ ] Preview de `terraquantum_ready.csv` devuelve `regional_scale_preflight.scale_class = "TOO_LARGE_SINGLE_INVERSION"` con grilla estimada visible
- [ ] `/invert` con `terraquantum_ready.csv` devuelve HTTP 422 con body estructurado y `recommended_action` claro
- [ ] `andes97_invert_subset.csv` (152 estaciones, subset) permite inversión, devuelve `scale_class = "REGIONAL_SCALE"` y warning de `estimated_depth_m` (~60 km)
- [ ] UI `GravityCsvPreviewPanel` muestra badge de escala y botón bloqueado para `TOO_LARGE_SINGLE_INVERSION`
- [ ] Reporte HTML documenta la clase de escala, si se bloqueó o permitió, y las limitaciones
- [ ] No se rompe ningún test de R3.5 — surveys locales con nx/nz ≤ 80 siguen funcionando sin cambios

---

## 15. Riesgos

### 15.1 Umbrales Arbitrarios
Los límites propuestos (10 km / 30 km / 100 km) son iniciales y conservadores. Datasets de exploración real pueden ser de 8 km o de 50 km y pertenecer a categorías diferentes según la resolución de medición. Los umbrales deben calibrarse en R3.7-G con datasets reales y feedback de geofísicos.

### 15.2 Datos Regionales Útiles para Geofísica
Un geofísico puede querer invertir datos a escala distrital o regional con parámetros explícitos (block_size grande, interpretación de corteza, no de yacimiento). El sistema no debe rechazar incondicionalmente esos casos; debe advertir y ofrecer opciones. Solo `TOO_LARGE_SINGLE_INVERSION` es un bloqueo incondicional por límite técnico del schema.

### 15.3 Tileado Requiere Diseño Adicional
El tileado de datasets regionales en múltiples inversiones independientes requiere decisiones sobre bordes de tile, estaciones en los límites, y consistencia de parámetros entre tiles. No trivializar: es una subproyecto propio (R3.7-F y más allá).

### 15.4 Depth Automático Físicamente Discutible
La fórmula `depth_m = max_extent × 0.6` es una heurística, no una constante geofísica. Podría reemplazarse en R3.7-B por una fórmula más conservadora que tenga en cuenta la escala: por ejemplo, `depth_m = min(max_extent * 0.3, 3000)` para LOCAL_SURVEY. Este cambio tiene impacto en todos los resultados existentes y debe discutirse con el responsable técnico antes de implementar.

### 15.5 UX: Evitar "Dataset Malo"
Todo el lenguaje de UI y reporte debe evitar la palabra "error" para datasets regionales. El mensaje correcto es: "Este dataset es de escala regional. No es inválido. Requiere un subset para inversión minera local." La clasificación es un servicio al usuario, no un rechazo.

### 15.6 No Tocar Inversión Geofísica Core
El solver (`exploration/gravimetry.py`), el foco (`exploration/focusing.py`) y MS-x no deben recibir cambios en ninguna subfase R3.7. El preflight es una capa de clasificación anterior al solver.

---

## Apéndice A — Respuestas a las Preguntas de Auditoría

**1. ¿Dónde se calcula el auto-grid?**  
`services/grid_calculator_service.py:compute_auto_grid()` (línea 103). Es llamado desde `services/gravity_import_service.py:import_gravity_csv_v1()` (línea 453).

**2. ¿Dónde aparecen nx, ny, nz?**  
Calculados en `_dimensions()` (línea 44 de `grid_calculator_service.py`). Devueltos en `AutoGrid` (`schemas/gravity_import_schema.py:85-101`). Usados como `effective_nx`, `effective_ny`, `effective_nz` en `api/gravity_import_api.py:731-734`.

**3. ¿Dónde se valida el límite <=80?**  
En el schema Pydantic `GeophysicsInvertInput` (`schemas/geophysics_schema.py:21-23`):
```python
nx: int = Field(..., ge=4, le=80)
ny: int = Field(..., ge=4, le=80)
nz: int = Field(..., ge=4, le=80)
```
Solo se valida en el momento de construir `GeophysicsInvertInput`, no antes.

**4. ¿Dónde se calcula depth_m?**  
`services/grid_calculator_service.py:127`:
```python
depth_m = _clamp(max_extent * 0.6, MIN_DEPTH_M, MAX_DEPTH_M)
# MIN_DEPTH_M = 1000, MAX_DEPTH_M = 100000
```

**5. ¿Cómo se relaciona depth_m con extent horizontal?**  
`depth_m = clamp(max(x_extent_m, z_extent_m) * 0.6, 1000, 100000)`. Relación directamente proporcional: a mayor extensión horizontal, mayor profundidad del modelo, hasta el tope de 100 km.

**6. ¿Dónde se devuelve el HTTP 422 actual?**  
`api/gravity_import_api.py:780-787`:
```python
except ValidationError as exc:
    raise HTTPException(
        status_code=422,
        detail={"message": "Invalid geophysics inversion input generated from gravity import.", "errors": exc.errors()},
    )
```
El error muestra el detalle interno de Pydantic (`nx: Value should be less than or equal to 80`) sin contexto de escala.

**7. ¿Dónde puede el preview anticipar que la inversión fallará?**  
El `/preview` ya calcula `auto_grid` y lo devuelve en la respuesta (`api/gravity_import_api.py:600-601`). Basta con evaluar `auto_grid.nx > 80 OR auto_grid.nz > 80` en el preview para anticipar el bloqueo. Actualmente no se hace esa evaluación.

**8. ¿Qué metadata ya existe para saber extent_x_m / extent_z_m?**  
- `coordinate_transform.x_extent_m` y `z_extent_m` (`schemas/gravity_import_schema.py:75-76`)
- `csv_analysis.sampling.area_km2` (`schemas/gravity_import_schema.py:19`)
- `auto_grid.nx`, `.ny`, `.nz`, `.depth_m`, `.block_size_m` (`schemas/gravity_import_schema.py:85-101`)
- En `/invert`: `x_extent` y `z_extent` calculados desde coordenadas transformadas (`api/gravity_import_api.py:738-739`)

**9. ¿Qué debe cambiar en la UX para no mostrar "Error 422" seco?**  
- En el frontend, interceptar la respuesta 422 y renderizar el bloque "Escala del Dataset" con el error estructurado en lugar del toast genérico de error.
- En el backend, estructurar el error 422 con `error: "REGIONAL_SCALE_PREFLIGHT"` (§8) antes de que Pydantic lo rechace.

**10. ¿Cómo documentar que un dataset es regional, no inválido?**  
- En el error HTTP 422: campo `"message"` con texto explícito "El dataset no es inválido; cubre una escala regional."
- En el reporte HTML: sección "Escala del Dataset" con límites y clase.
- En `gravity_import_metadata.json`: campo `regional_scale_preflight.scale_class`.
- En la UI: badge de escala (no ícono de error) con label "ESCALA REGIONAL" en lugar de "Error".

---

## Apéndice B — Archivos Relevantes

| Archivo | Propósito en R3.7 |
|---|---|
| `terraquantum-backend/services/grid_calculator_service.py` | Origen de auto-grid y depth_m — leer, no modificar en R3.7-A |
| `terraquantum-backend/schemas/gravity_import_schema.py` | Agregar `RegionalScalePreflight` en R3.7-B |
| `terraquantum-backend/schemas/geophysics_schema.py` | Define constante <=80; no modificar |
| `terraquantum-backend/api/gravity_import_api.py` | Integrar preflight en `/preview` (R3.7-B) y `/invert` (R3.7-C) |
| `terraquantum-web/componentes/GravityCsvPreviewPanel.tsx` | Agregar bloque "Escala del Dataset" en R3.7-D |
| `terraquantum-web/lib/terraquantum/frontendApi.ts` | Agregar tipo `RegionalScalePreflight` en R3.7-D |
| `benchmarks/public_gravity_b1/terraquantum_ready.csv` | Test QA R3.7-G — full file → TOO_LARGE |
| `benchmarks/public_gravity_b1/normalized/andes97_invert_subset.csv` | Test QA R3.7-G — subset → REGIONAL_SCALE + warn depth |

---

*Documento generado: 2026-05-22. Solo lectura de archivos productivos. Sin modificaciones de código.*
