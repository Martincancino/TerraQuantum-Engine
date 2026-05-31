# TERRAQUANTUM — R3 DEM CO-REGISTRADO, VOXEL ABSOLUTE ELEVATION Y TERRENO REAL POR FOOTPRINT

**Versión:** 1.0  
**Fecha:** 2026-05-19  
**Autor:** Claude Code — Auditoría completa de código fuente + diseño arquitectónico  
**Estado:** ESPECIFICACIÓN EJECUTABLE — ACTIVA  
**Fuentes:** Código auditado en solo lectura: `terrain_api.py`, `satellite_service.py`, `block_model_api.py`, `block_model_service.py`, `block_model_store.py`, `geo_utils.py`, `coordinate_transform_service.py`, `coordinate_transform_real.py`, `gravity_import_service.py`, `project_schema.py`, `terrain_schema.py`, `gravity_import_schema.py`, `tests/` (22 archivos), `frontendApi.ts`, `useAppStore.ts`, `GeoDashboard.tsx`. Documentos de referencia: `TERRAQUANTUM_R1_SPATIAL_CONTRACT_SPEC.md`, `TERRAQUANTUM_R2_CRS_UTM_PYPROJ_SPEC.md`, `TERRAQUANTUM_HVC_VALIDATION_V1.md`, `TERRAQUANTUM_INDUSTRIAL_REALITY_BIBLE.md`.

---

> **Propósito de este documento:**  
> Especificación técnica completa y ejecutable para implementar R3 — DEM co-registrado, `voxel_absolute_elevation` y terreno real por footprint. Define qué existe, qué falta, qué endpoints/servicios cambiar, qué columnas agregar al parquet, cómo calcular la elevación absoluta por voxel, y en qué orden ejecutar. Cada sección termina en criterios concretos o decisiones explícitas.

---

## 1. Dictamen R3

### 1.1 Veredicto técnico

R1 y R2 están cerrados y verificados. El sistema tiene:
- footprint real con 4 esquinas WGS84 (`utm_pyproj`, `georef_confidence = "HIGH"`)
- `CrsContract` con `epsg_code = 32719`, `crs_source = "user_declared"`
- `transform_utm_to_wgs84()` y `transform_wgs84_to_utm()` con pyproj funcionando
- R2.3 runtime PASS: `footprint.source = "utm_pyproj"`, `georef_confidence = HIGH`, `input_crs = EPSG:32719`

**Sin embargo, el modelo sigue "flotando" sin elevación real:**

- El DEM se pide usando un bbox calculado independientemente del `project_footprint` de R2
- El terrain endpoint no usa los corners reales del footprint — usa `center_lat/lon` + extent + 20% buffer propio
- `block_model.parquet` no tiene columnas `lat`, `lon`, `surface_elevation_masl`, `depth_below_surface_m`, ni `voxel_elevation_masl`
- El solver usa `y_m` como profundidad positiva hacia abajo, pero `y_m = 0` no está referenciado a ninguna elevación geodésica real
- La escena 3D muestra el modelo sobre terreno de Atacama (latitud HVC incorrecta) sin co-registro
- No existe función `sample_dem_elevation()` ni lógica de muestreo DEM por posición de voxel

### 1.2 Decisión principal de R3

R3 construye la **cadena de elevación absoluta** sobre el contrato espacial que R1/R2 establecieron.

R3 hace:
1. Terrain endpoint usa `project_footprint` real (corners WGS84) si `georef_confidence ≥ MEDIUM` con pyproj
2. Metadata DEM extendida: min/max/mean elevation, cell sizes, fuente, warnings
3. DEM se persiste como `terrain_metadata.json` (sin guardar la matrix entera si es grande)
4. Función `sample_dem_elevation(x_m, z_m)` con bilinear interpolation
5. `block_model.parquet` recibe columnas: `surface_elevation_masl`, `depth_below_surface_m`, `voxel_elevation_masl`, `lat`, `lon`
6. `/block-model` expone los campos nuevos en el JSON de celdas
7. Fallback honesto si `georef_confidence = LOW/MISSING`: advertencia sin inventar elevación

R3 NO hace (queda para R4+):
- Cambiar solver LSQR
- Cambiar MS-x
- Host volume siguiendo DEM (mesh real sin BoxGeometry) → R3-FE-4 es solo el plan, no la implementación
- Cambiar Scene3D para usar elevación (eso es R3-FE-3, subfase final del ciclo R3)
- Diseño minero ni economía
- GEE para índices espectrales (ya funciona separado)
- Slices profesionales (R4)

---

## 2. Estado actual DEM/terrain

### 2.1 Respuestas a las preguntas de auditoría

**A1. ¿Cómo se pide hoy el terreno?**

`GET /projects/{project_id}/terrain` → `get_terrain_data(project_id)` en `satellite_service.py`.

Flujo actual:
1. Lee `latitude/longitude` de `project_meta.json` (punto central).
2. Lee extensión del último `source_gravity.csv` (columnas x_m/z_m) → `_derive_project_extent()`.
3. Llama `compute_bbox(center_lat, center_lon, extent_x_m, extent_z_m, buffer=0.20)` → bbox con 20% buffer, equirectangular.
4. Consulta GEE (Copernicus GLO-30) sobre ese bbox → DEM 32×32.
5. Retorna `TerrainResponse`.

**Problema clave:** El bbox del terrain se calcula **independientemente del `project_footprint` de R2**. Son dos cálculos paralelos, potencialmente inconsistentes. Si el footprint tiene `source = "utm_pyproj"` con corners exactos, el terrain sigue usando el centro + equirectangular propio.

**A2. ¿El terrain endpoint usa lat/lon central o footprint?**

Usa **lat/lon central únicamente** (`_read_project_center()` lee solo `latitude/longitude` del meta). No lee `footprint` del proyecto. No usa `footprint.sw/ne` como corners del bbox.

**A3. ¿Qué metadata DEM devuelve hoy?**

`TerrainMetadata` (schema en `terrain_schema.py`):
```python
class TerrainMetadata(BaseModel):
    bbox: BBoxData          # min_lat, max_lat, min_lon, max_lon
    resolution_m: float     # max(extent_x, extent_z) / 32
    source: str             # "gee_v1" | "mock_v1" | "mock_v1_gee_fallback"
    dem_rows: int           # siempre 32
    dem_cols: int           # siempre 32
    center_lat: float
    center_lon: float
    extent_x_m: float
    extent_z_m: float
```

**Lo que NO retorna:** `min_elevation_m`, `max_elevation_m`, `mean_elevation_m`, `cell_size_x_m`, `cell_size_z_m`, `georef_confidence`, `footprint_source`, `warnings`, `dem_bbox_margin_factor`.

**A4. ¿DEM matrix tiene georreferenciación por celda?**

No. La `dem_matrix` es un array 32×32 de floats. No hay información de qué lat/lon corresponde a cada celda. La correspondencia celda→lat/lon debe inferirse del bbox y las dimensiones del grid.

**A5. ¿terrainData incluye bbox/corners?**

Incluye `bbox` (min_lat, max_lat, min_lon, max_lon) pero no corners individuales por celda, ni dimensiones de celda individuales. `cell_size_x_m = extent_x_m / 32`, `cell_size_z_m = extent_z_m / 32` se puede calcular, pero no está explícito.

**A6. ¿satellite_service puede aceptar bbox/polygon?**

**No directamente.** La función pública `get_terrain_data(project_id)` solo acepta `project_id`. Internamente, `_fetch_gee_terrain(bbox, extent_x_m, extent_z_m, center_lat)` sí acepta un bbox dict — pero ese bbox se calcula siempre con el método propio. Para R3, `get_terrain_data()` debe aceptar un argumento `footprint_override` opcional.

**A7. ¿DEM se guarda en project/run o solo se devuelve?**

**Solo se devuelve.** No hay persistencia del DEM ni de su metadata extendida. Cada llamada al endpoint recalcula el DEM desde GEE. Esto implica que:
- El bloque de enriquecimiento del parquet no puede referenciarse al DEM calculado en otra sesión
- No hay audit trail del DEM usado para cada run
- Para R3, se necesita persistir al menos `terrain_metadata.json` por run

**A8. ¿Textura satelital usa el mismo bbox que DEM?**

Sí. En `_fetch_gee_terrain()`, tanto el DEM GLO-30 como el Sentinel-2 usan la misma variable `region` derivada del `bbox` dict. Si cambiamos el bbox, ambos cambiarán juntos (correcto para R3).

### 2.2 Tabla resumen de estado actual

| Capacidad | Estado actual | R3 |
|-----------|---------------|-----|
| Terrain por punto central | ✅ funciona | Mantener como fallback |
| Terrain por footprint real | ❌ no existe | Implementar en R3-BE-1 |
| DEM bbox incluye margin configurable | ❌ hardcoded 20% | Parametrizar: `terrain_margin_factor` |
| Metadata DEM con min/max/mean elevation | ❌ no existe | Agregar en R3-BE-1 |
| DEM persistido por run | ❌ no existe | `terrain_metadata.json` en R3-BE-3 |
| sample_dem_elevation() | ❌ no existe | Implementar en R3-BE-2 |
| Voxel elevation_masl en parquet | ❌ no existe | Agregar en R3-BE-4 |
| /block-model expone elevation fields | ❌ no existe | Agregar en R3-BE-5 |

---

## 3. Estado actual block model

### 3.1 Columnas de `block_model.parquet`

Del código auditado en `block_model_service.py`:

| Columna | Tipo | Descripción | R3 |
|---------|------|-------------|-----|
| `ix` | int | Índice de bloque en eje X (E-O) | Mantener |
| `iy` | int | Índice de bloque en eje Y (profundidad) | Mantener |
| `iz` | int | Índice de bloque en eje Z (N-S) | Mantener |
| `x` / `x_m` | float | Posición en metros locales, eje X (E-O) | Mantener |
| `y` / `y_m` | float | Profundidad en metros (positiva hacia abajo) | Mantener |
| `z` / `z_m` | float | Posición en metros locales, eje Z (N-S) | Mantener |
| `density` | float | Contraste de densidad relativa [g/cm³] | Mantener |
| `rho` | float | Alias de density | Mantener |
| `probability` | float | Score de probabilidad relativa [0-1] | Mantener |
| `visual_score` | float | Score visual combinado | Mantener |
| `grade` | float | Ley (cuando aplica) | Mantener |
| `domain` | int | Dominio geológico | Mantener |
| `tonnage` | float | Tonelaje estimado | Mantener |

**Columnas ausentes para R3:**

| Columna nueva | Tipo | Descripción |
|---------------|------|-------------|
| `lat` | float | Latitud WGS84 del centro del voxel |
| `lon` | float | Longitud WGS84 del centro del voxel |
| `surface_elevation_masl` | float | Elevación DEM en (x_m, z_m) [metros s.n.m.] |
| `depth_below_surface_m` | float | Profundidad desde superficie DEM (= y_m) |
| `voxel_elevation_masl` | float | Elevación absoluta del voxel = surface_elevation_masl - y_m |
| `georef_confidence` | str | Nivel de confianza georef heredado del proyecto |
| `dem_source` | str | Fuente del DEM ("gee_v1", "mock_v1", etc.) |
| `dem_sample_method` | str | Método de muestreo ("bilinear", "nearest") |
| `spatial_reference_warning` | str | Warning si hay limitaciones espaciales |

### 3.2 Orientación del sistema de coordenadas del modelo

Confirmado por comentario en `block_model_service.py` línea 393:
```python
# Backend: y es profundidad positiva hacia abajo.
# Three.js: y es vertical positiva hacia arriba.
cx = x_m - x_center
cy = y_center - y_m   # Three.js: y invertida
cz = z_m - z_center
```

**Conclusión:**
- `x_m` → eje Este-Oeste (metros locales desde borde SW)
- `y_m` → profundidad positiva hacia abajo (0 = superficie del survey)
- `z_m` → eje Norte-Sur (metros locales desde borde SW)
- El voxel en `iy = 0` (y_m ≈ block_size/2) está justo bajo la superficie
- `depth_below_surface_m = y_m` (ya es profundidad, no se necesita inversión)

### 3.3 Dónde se filtra/anomaly/full

En `block_model_service.py:build_block_model_response()`:
- mode `exploration` → `select_limited_exploration_view()` con limit=5000
- mode `full` → retorna todo el dataframe
- mode `anomaly` → lee `block_model_anomaly.parquet` separado
- mode `economic` → filtra por `grade > 0.3`

### 3.4 Dónde se transforma a JSON para frontend

En `build_block_model_response()`, líneas 378-424: loop `for row in df_view.iter_rows(named=True)` → construye dict por celda → lista `cells`. Los campos `lat`, `lon`, `voxel_elevation_masl`, etc. **no existen** hoy.

---

## 4. Datos disponibles desde R1/R2

### 4.1 Fuentes disponibles en `project_meta.json` post-R2.3

```json
{
  "project_id": "...",
  "latitude": -22.28,
  "longitude": -68.89,
  "crs": "EPSG:4326",
  "georef_confidence": "HIGH",
  "georef_type": "csv_utm",
  "utm_zone": "19S",
  "input_crs": "EPSG:32719",
  "epsg_code": 32719,
  "crs_source": "user_declared",
  "utm_hemisphere": "S",
  "footprint": {
    "source": "utm_pyproj",
    "confidence": "HIGH",
    "crs": "EPSG:4326",
    "type": "bbox",
    "center_lat": ...,
    "center_lon": ...,
    "extent_x_m": ...,
    "extent_z_m": ...,
    "utm_zone": "19S",
    "epsg_code": 32719,
    "crs_source": "user_declared",
    "crs_confidence": "HIGH",
    "sw": {"lat": ..., "lon": ...},
    "se": {"lat": ..., "lon": ...},
    "ne": {"lat": ..., "lon": ...},
    "nw": {"lat": ..., "lon": ...}
  }
}
```

### 4.2 Funciones disponibles en `coordinate_transform_real.py` post-R2.3

```python
# Disponibles y verificadas (pyproj funcionando):
transform_utm_to_wgs84(easting, northing, utm_zone="19S", epsg_code=32719) → (lat, lon)
transform_wgs84_to_utm(lat, lon, utm_zone="19S", epsg_code=32719) → (easting, northing)
compute_utm_footprint_with_pyproj(...) → dict compatible con ProjectFootprint
get_epsg_from_utm(zone_number, hemisphere) → int
parse_utm_zone_string("19S") → (19, "S")
validate_utm_easting_northing(easting, northing, zone_num, hemisphere) → [warnings]
approx_dist_km(lat1, lon1, lat2, lon2) → float (haversine)
```

### 4.3 Datos de grilla disponibles en `inputs.json` del run

Desde `HVC_VALIDATION_V1.md` y código auditado:
```json
{
  "depth": 29808,
  "nx": 32,
  "ny": 20,
  "nz": 32,
  "block_size": 1558,
  "cutoff_radius": 6228.1
}
```

Estos parámetros permiten calcular la posición de cada voxel en metros locales:
```
x_m = ix * block_size + block_size/2      (centro del voxel)
y_m = iy * block_size + block_size/2      (profundidad del centro)
z_m = iz * block_size + block_size/2      (centro del voxel)
```

### 4.4 Lo que falta para R3

| Necesidad | Estado |
|-----------|--------|
| Footprint corners WGS84 reales | ✅ Disponible (utm_pyproj R2.3) |
| pyproj transform UTM ↔ WGS84 | ✅ Disponible y funcionando |
| EPSG code del proyecto | ✅ Disponible |
| Terrain por bbox custom | ❌ No existe (terrain usa solo center+extent) |
| DEM persistido por run | ❌ No existe |
| sample_dem_elevation() | ❌ No existe |
| Columnas elevation en parquet | ❌ No existen |
| API block-model expone elevation | ❌ No existe |

---

## 5. Problema que R3 resuelve

### 5.1 El problema central

Actualmente existe una **discontinuidad entre el contrato espacial (R1/R2) y el modelo 3D**:

- El footprint sabe dónde está el survey (corners reales UTM pyproj, HIGH confidence)
- El terrain sabe qué elevación tiene la superficie en el área
- El block model sabe la profundidad de cada voxel
- **Pero estos tres objetos no están conectados entre sí**

Consecuencia:
- El modelo puede verse visualmente debajo del terreno real o por encima de él
- No es posible decir a qué elevación (metros s.n.m.) está cada voxel
- Los slices verticales no tienen profundidad real referenciada a la superficie topográfica
- El host volume (envolvente del modelo) es una caja artificial, no la topografía real

### 5.2 Qué establece R3

1. **DEM por footprint real**: el terrain endpoint usa los corners WGS84 del `project_footprint` (no solo el centro)
2. **DEM con margin explícito**: `terrain_margin_factor = 1.5` → el DEM cubre 50% más que el modelo
3. **Metadata DEM extendida**: min/max/mean elevation, cell sizes en metros, fuente, confidence
4. **sample_dem_elevation**: función que mapea posición de voxel (x_m, z_m) → elevación del DEM
5. **voxel_absolute_elevation**: `voxel_elevation_masl = surface_elevation_at(x_m, z_m) - y_m`
6. **Columnas nuevas en parquet**: `lat`, `lon`, `surface_elevation_masl`, `depth_below_surface_m`, `voxel_elevation_masl`
7. **API enriquecida**: `/block-model` expone los campos nuevos si están disponibles

---

## 6. Problema que R3 NO resuelve

| Problema | Fase correcta |
|----------|---------------|
| Host volume como mesh siguiendo DEM (sin BoxGeometry) | R3-FE-4 plan → R4 implementación |
| Scene3D posiciona voxeles usando elevation_masl real | R3-FE-3 → depende de datos R3 disponibles |
| Slices con profundidad real | R4 |
| Colorbar con densidad absoluta calibrada | R4 |
| Cambio al solver LSQR | No en R3 |
| Cambio a MS-x | No en R3 |
| Confirmación de mineral | Nunca automático |
| Economía / NPV / LOM | R5+ |
| GEE para índices espectrales | Ya existe separado, no cambiar |
| Terrain para proyectos con georef MISSING como si fuera real | No en R3 — warning obligatorio |

---

## 7. Arquitectura DEM por footprint

### 7.1 Lógica de decisión en terrain endpoint

```
project_meta.footprint.confidence
    ├── HIGH → usar footprint corners reales (utm_pyproj o latlon)
    │          → DEM bbox = footprint bbox * terrain_margin_factor
    ├── MEDIUM → usar footprint corners con warning "estimado"
    │           → DEM bbox = footprint bbox * terrain_margin_factor
    │           → warning: "Terreno basado en footprint estimado. Verificar co-registro."
    ├── LOW → usar center + extent (método actual)
    │          → warning: "Terreno solo contexto visual. Footprint de baja confianza."
    └── MISSING → usar center + extent si lat/lon disponible
                → warning: "Sin georreferenciación. Terreno no co-registrado."
```

### 7.2 Parámetro `terrain_margin_factor`

```python
TERRAIN_MARGIN_FACTOR = 1.5  # DEM cubre 50% más que el modelo en cada dirección

# En práctica:
# Si footprint extent_x_m = 50000 m, el DEM bbox tiene ancho = 50000 * 1.5 = 75000 m
# Esto garantiza que el terreno cubre el modelo completamente + margen para visualización
```

Justificación:
- El modelo gravimétrico tiene efectos de borde → el terreno visible debe exceder el modelo
- El margin actual es 20% (hardcoded) → insuficiente para host volume futuro
- 50% es un balance entre cobertura visual y costo de consulta GEE

### 7.3 Modificaciones a `satellite_service.get_terrain_data()`

Firma nueva (compatible con la actual — parámetros con defaults):

```python
def get_terrain_data(
    project_id: str,
    footprint_override: dict | None = None,
    terrain_margin_factor: float = TERRAIN_MARGIN_FACTOR,
) -> TerrainResponse:
    """
    Si footprint_override es None, lee el footprint del project_meta.
    Si footprint.confidence >= MEDIUM y tiene corners reales, usa corners.
    Si no, fallback a center + extent (método actual).
    """
```

### 7.4 Función `_footprint_to_bbox(footprint, margin_factor)`

Nueva función en `satellite_service.py` (o en `core/geo_utils.py`):

```python
def _footprint_to_bbox(
    footprint: dict,
    margin_factor: float = 1.5,
) -> tuple[dict, list[str]]:
    """
    Convierte un ProjectFootprint dict → bbox dict para terrain request.

    Si footprint tiene corners reales (sw/ne WGS84), usa los corners exactos y aplica margin.
    Si footprint.confidence = HIGH (utm_pyproj): margin sobre bbox real.
    Si footprint.confidence = MEDIUM: margin + warning "estimado".
    Si footprint.confidence = LOW/MISSING: fallback a center + extent.

    Returns (bbox_dict, warnings_list).
    """
    confidence = footprint.get("confidence", "MISSING").upper()
    sw = footprint.get("sw") or {}
    ne = footprint.get("ne") or {}

    if confidence in ("HIGH", "MEDIUM") and sw.get("lat") and ne.get("lat"):
        # Usar corners reales con margin
        lat_range = abs(ne["lat"] - sw["lat"])
        lon_range = abs(ne["lon"] - sw["lon"])
        lat_margin = lat_range * (margin_factor - 1.0) / 2.0
        lon_margin = lon_range * (margin_factor - 1.0) / 2.0
        bbox = {
            "min_lat": sw["lat"] - lat_margin,
            "max_lat": ne["lat"] + lat_margin,
            "min_lon": sw["lon"] - lon_margin,
            "max_lon": ne["lon"] + lon_margin,
        }
        warnings = []
        if confidence == "MEDIUM":
            warnings.append("Footprint estimado — co-registro terrain/modelo aproximado.")
        return bbox, warnings

    # Fallback: center + extent equirectangular
    center_lat = footprint.get("center_lat")
    center_lon = footprint.get("center_lon")
    extent_x = footprint.get("extent_x_m", 0)
    extent_z = footprint.get("extent_z_m", 0)
    if center_lat and center_lon and extent_x > 0:
        # Usa compute_bbox existente con margin_factor como buffer
        from core.geo_utils import compute_bbox
        bbox = compute_bbox(center_lat, center_lon, extent_x, extent_z, buffer=margin_factor - 1.0)
        return bbox, ["Footprint de baja confianza — terrain solo contexto visual."]

    return None, ["Sin footprint válido — terrain no disponible."]
```

---

## 8. DEM metadata y persistencia

### 8.1 Schema extendido `TerrainMetadata` (modificar `terrain_schema.py`)

```python
class TerrainMetadata(BaseModel):
    # Campos actuales (mantener):
    bbox: BBoxData
    resolution_m: float
    source: str
    dem_rows: int
    dem_cols: int
    center_lat: float
    center_lon: float
    extent_x_m: float
    extent_z_m: float

    # Campos nuevos R3:
    min_elevation_m: Optional[float] = None   # mín DEM en el bbox
    max_elevation_m: Optional[float] = None   # máx DEM en el bbox
    mean_elevation_m: Optional[float] = None  # media DEM en el bbox
    cell_size_x_m: float = 0.0               # ancho de celda DEM en metros
    cell_size_z_m: float = 0.0               # alto de celda DEM en metros
    footprint_source: Optional[str] = None   # "utm_pyproj" | "center_extent" | etc.
    georef_confidence: str = "MISSING"       # confianza heredada del proyecto
    terrain_margin_factor: float = 1.5       # factor de margen usado
    warnings: List[str] = Field(default_factory=list)
```

### 8.2 TerrainResponse extendida

```python
class TerrainResponse(BaseModel):
    project_id: str
    dem_matrix: list[list[float]]
    texture_url: str
    metadata: TerrainMetadata
    # run_id: Optional[str] = None  # para asociar el terrain a un run específico
```

### 8.3 Cálculo de cell_size_x_m y cell_size_z_m

```python
# En satellite_service.py, después de obtener el DEM:
bbox_lat_range_m = (bbox["max_lat"] - bbox["min_lat"]) * METERS_PER_DEG_LAT
bbox_lon_range_m = (bbox["max_lon"] - bbox["min_lon"]) * METERS_PER_DEG_LAT * cos(center_lat_rad)
cell_size_z_m = bbox_lat_range_m / DEM_ROWS   # metros por fila
cell_size_x_m = bbox_lon_range_m / DEM_COLS   # metros por columna
```

### 8.4 Persistencia: `terrain_metadata.json`

R3 persiste la metadata del DEM (sin la matrix entera) en el directorio del proyecto:

```
terraquantum-backend/data/projects/{project_id}/terrain_metadata.json
```

Formato:
```json
{
  "project_id": "...",
  "generated_at": "2026-05-19T...",
  "bbox": {
    "min_lat": ..., "max_lat": ...,
    "min_lon": ..., "max_lon": ...
  },
  "dem_rows": 32,
  "dem_cols": 32,
  "cell_size_x_m": ...,
  "cell_size_z_m": ...,
  "min_elevation_m": ...,
  "max_elevation_m": ...,
  "mean_elevation_m": ...,
  "source": "gee_v1",
  "footprint_source": "utm_pyproj",
  "georef_confidence": "HIGH",
  "terrain_margin_factor": 1.5,
  "warnings": [],
  "model_extent_x_m": ...,
  "model_extent_z_m": ...,
  "model_sw_lat": ...,
  "model_sw_lon": ...
}
```

**Nota:** La `dem_matrix` (32×32 = 1024 floats) es ~8 KB en JSON — acceptable guardarla también si facilita el enriquecimiento offline del parquet. Si el proyecto tiene runs múltiples, solo se guarda la metadata sin la matrix.

**Decisión R3:** Guardar la matrix como `terrain_dem_matrix.json` separado con un flag en la metadata:
```json
{ "dem_matrix_path": "terrain_dem_matrix.json" }
```
Esto permite que `R3-BE-4` lea el DEM sin consultar GEE nuevamente.

---

## 9. Sampling DEM

### 9.1 Función `sample_dem_elevation()`

Nueva función en `core/geo_utils.py` o `services/terrain_sampling_service.py`:

```python
def sample_dem_elevation(
    dem_matrix: list[list[float]],
    dem_metadata: dict,
    x_m: float,
    z_m: float,
    model_extent_x_m: float,
    model_extent_z_m: float,
    method: str = "bilinear",
) -> tuple[float, str]:
    """
    Muestrea la elevación del DEM en la posición (x_m, z_m) del modelo local.

    Args:
        dem_matrix: matriz DEM rows×cols (rows = Norte-Sur, cols = Oeste-Este)
        dem_metadata: dict con bbox, dem_rows, dem_cols, cell_size_x_m, cell_size_z_m,
                      model_extent_x_m, model_extent_z_m, model_sw_lat, model_sw_lon
        x_m: posición local en el modelo (Este-Oeste, 0 = borde SW)
        z_m: posición local en el modelo (Norte-Sur, 0 = borde SW)
        model_extent_x_m: extensión total del modelo en X
        model_extent_z_m: extensión total del modelo en Z
        method: "bilinear" | "nearest"

    Returns:
        (elevation_masl, warning_str)
        warning_str es "" si OK, mensaje si hubo problemas.
    """
```

### 9.2 Mapeo de posición de voxel a índice DEM

La lógica central del mapeado:

```
Coordenadas del modelo:
  - x_m ∈ [0, model_extent_x_m]   → Este-Oeste
  - z_m ∈ [0, model_extent_z_m]   → Norte-Sur

El DEM cubre:
  - bbox_x_m = (max_lon - min_lon) * meters_per_deg_lon  → más ancho que el modelo
  - bbox_z_m = (max_lat - min_lat) * METERS_PER_DEG_LAT  → más alto que el modelo

Offset SW del modelo dentro del DEM bbox:
  - model_sw está en la posición (sw_lat, sw_lon) del footprint
  - sw está dentro del DEM bbox por definición (margin_factor > 1.0)

Posición del voxel en el DEM:
  x_in_bbox_m = offset_x_m + x_m   donde offset_x = distancia de DEM_min_lon a model_sw_lon
  z_in_bbox_m = offset_z_m + z_m

Índice de celda DEM:
  col = (x_in_bbox_m / bbox_x_m) * dem_cols
  row = ((bbox_z_m - z_in_bbox_m) / bbox_z_m) * dem_rows  ← invertir: fila 0 = Norte (máx lat)
```

### 9.3 Bilinear interpolation

```python
def _bilinear_interp(matrix, row_f, col_f):
    rows = len(matrix)
    cols = len(matrix[0]) if rows > 0 else 0
    row0 = max(0, min(int(row_f), rows - 2))
    col0 = max(0, min(int(col_f), cols - 2))
    row1, col1 = row0 + 1, col0 + 1
    dr = row_f - row0
    dc = col_f - col0
    # bilinear weights
    v00 = matrix[row0][col0]
    v01 = matrix[row0][col1]
    v10 = matrix[row1][col0]
    v11 = matrix[row1][col1]
    return (
        v00 * (1 - dr) * (1 - dc) +
        v01 * (1 - dr) * dc +
        v10 * dr * (1 - dc) +
        v11 * dr * dc
    )
```

### 9.4 Manejo de casos borde

| Caso | Comportamiento |
|------|---------------|
| Voxel dentro del DEM bbox | Interpolación bilinear normal |
| Voxel justo en borde del DEM | Clamp a índice válido + warning |
| Voxel fuera del DEM (si margin es insuficiente) | Retornar media del DEM + warning "voxel fuera del DEM" |
| DEM es mock (todos ceros) | Retornar 0.0 + warning "DEM mock — elevación conceptual" |
| dem_metadata faltante | Retornar None + warning "sin metadata DEM" |

### 9.5 Garantizar que el DEM cubre el modelo

Con `terrain_margin_factor = 1.5`:
- DEM extent = 1.5× model extent en cada dirección
- Margen extra = 0.25× model extent en cada borde (25% de cada lado)
- Para HVC: model ≈ 50km → DEM ≈ 75km → margen ≈ 12.5km por lado
- Ningún voxel puede estar fuera del DEM si la metadata es consistente

**Verificación en `R3-BE-4`:** antes del enriquecimiento, verificar que:
```python
assert model_extent_x_m <= (dem_bbox_x_m / terrain_margin_factor)
assert model_extent_z_m <= (dem_bbox_z_m / terrain_margin_factor)
```

---

## 10. Voxel absolute elevation

### 10.1 Fórmula central de R3

```python
# Por cada voxel en block_model.parquet:

# 1. Posición local del voxel (centro del bloque)
x_m = ix * block_size_m + block_size_m / 2.0   # metros locales E-O
y_m = iy * block_size_m + block_size_m / 2.0   # profundidad (positiva abajo)
z_m = iz * block_size_m + block_size_m / 2.0   # metros locales N-S

# 2. Elevación DEM en la posición horizontal del voxel
surface_elevation_masl = sample_dem_elevation(dem_matrix, dem_metadata, x_m, z_m)

# 3. Profundidad desde superficie: y_m ya ES la profundidad
depth_below_surface_m = y_m  # positiva hacia abajo

# 4. Elevación absoluta del voxel
voxel_elevation_masl = surface_elevation_masl - depth_below_surface_m

# 5. Coordenadas geográficas del voxel (si CRS ≥ MEDIUM)
# Para UTM: transformar (x_raw + offset_easting, z_raw + offset_northing) → (lat, lon)
# Para lat/lon: interpolar desde footprint corners
lat, lon = transform_voxel_to_wgs84(x_m, z_m, project_meta)
```

### 10.2 Significado de `y_m` — aclaración definitiva

Del código auditado (`block_model_service.py`, línea 393):
```python
# Backend: y es profundidad positiva hacia abajo.
cy = y_center - y_m   # invertida para Three.js
```

`y_m = 0` → **superficie del survey** (y=0 del solver LSQR).
`y_m = block_size/2` → voxel en `iy=0`, a `block_size/2` metros bajo la superficie.
`y_m = depth_m` → voxel más profundo del modelo.

`depth_below_surface_m = y_m` **sin inversión adicional**. No es necesario calcular nada extra.

### 10.3 Transformar posición local de voxel a WGS84

Para proyectos con `input_crs = EPSG:32719` (UTM 19S):
```python
# Se necesita el offset UTM del borde SW del modelo
# De gravity_import_metadata.json → coordinate_transform:
easting_min = ct.x_min_raw    # mínimo easting del CSV
northing_min = ct.z_min_raw   # mínimo northing del CSV

# Posición UTM del voxel:
voxel_easting = easting_min + x_m
voxel_northing = northing_min + z_m

# Transformar a WGS84:
lat, lon = transform_utm_to_wgs84(voxel_easting, voxel_northing, epsg_code=32719)
```

Para proyectos `local_meters` con ancla lat/lon (LOW confidence):
```python
# Usar equirectangular (no es exacto, pero honesto con el nivel de confianza)
# Desde el footprint: sw_lat, sw_lon son el punto de referencia del modelo
lat = sw_lat + (z_m / METERS_PER_DEG_LAT)
lon = sw_lon + (x_m / (METERS_PER_DEG_LAT * cos(lat_rad)))
# Warning: "Coordenadas lat/lon aproximadas — footprint de baja confianza"
```

Para proyectos con `georef_confidence = MISSING`:
```python
lat = None
lon = None
# No inventar lat/lon. Columnas quedan como None.
```

---

## 11. Nuevas columnas block_model

### 11.1 Columnas a agregar

| Columna | Tipo | Descripción | Calculable cuando |
|---------|------|-------------|-------------------|
| `lat` | float \| None | Latitud WGS84 del centro del voxel | confidence ≥ LOW + lat/lon central |
| `lon` | float \| None | Longitud WGS84 del centro del voxel | confidence ≥ LOW + lat/lon central |
| `surface_elevation_masl` | float \| None | Elevación DEM en (x_m, z_m) [m s.n.m.] | DEM disponible |
| `depth_below_surface_m` | float | Profundidad desde superficie (= y_m) | Siempre |
| `voxel_elevation_masl` | float \| None | surface_elevation_masl - y_m [m s.n.m.] | DEM disponible |
| `georef_confidence` | str | Confianza heredada ("HIGH"/"MEDIUM"/"LOW"/"MISSING") | Siempre |
| `dem_source` | str \| None | Fuente del DEM ("gee_v1", "mock_v1", None) | Cuando DEM disponible |
| `dem_sample_method` | str \| None | Método de muestreo ("bilinear", "nearest", None) | Cuando DEM disponible |
| `spatial_reference_warning` | str \| None | Warning si hay limitación espacial | Si existe |

### 11.2 Dónde agregar estas columnas

**Opción A (recomendada):** Agregar en el momento del enriquecimiento post-inversión, como paso nuevo en el pipeline después de guardar el parquet base. La inversión LSQR no se toca. Solo se agrega un paso de enriquecimiento que lee el parquet, agrega columnas, y lo sobreescribe.

**Opción B:** Agregar bajo demanda en el momento de la consulta API (`/block-model`). Solo se calculan si el terrain_metadata está disponible. No se persisten.

**Decisión R3:** Opción A para las columnas de elevación (persisten en el parquet), porque:
- Permite audit trail de qué DEM se usó
- El enriquecimiento no es repetible con exactitud si el DEM cambia entre consultas
- El costo de cómputo es bajo (32×20×32 = 20480 voxels máximo)

**Para `lat/lon`:** también Opción A si `georef_confidence ≥ MEDIUM` (pyproj exacto). Para LOW, Opción B (aproximación sin persistir).

### 11.3 Columnas que van a ambos parquets

Las columnas se agregan tanto a `block_model.parquet` (full) como se heredan automáticamente a `block_model_anomaly.parquet` (que es un subconjunto del full).

**No modificar `block_model_focusing.parquet` en R3** → solo contiene densidades MS-x, agregar elevación en R4 si se decide.

---

## 12. API `/block-model` extendida

### 12.1 Campos nuevos en la respuesta

Cuando el parquet tiene las columnas nuevas, `build_block_model_response()` las expone en cada celda:

```python
cell = {
    # ... campos actuales ...
    "cx": cx, "cy": cy, "cz": cz,
    "x_m": x_m, "y_m": y_m, "z_m": z_m,
    "density": density,
    # Nuevos R3 (solo si existen en el parquet):
    "lat": row.get("lat"),                                   # float | None
    "lon": row.get("lon"),                                   # float | None
    "surface_elevation_masl": row.get("surface_elevation_masl"),   # float | None
    "depth_below_surface_m": row.get("depth_below_surface_m"),     # float | None
    "voxel_elevation_masl": row.get("voxel_elevation_masl"),       # float | None
    "georef_confidence": row.get("georef_confidence"),             # str | None
    "dem_source": row.get("dem_source"),                           # str | None
    "spatial_reference_warning": row.get("spatial_reference_warning"), # str | None
}
```

### 12.2 Campos nuevos en la metadata de la respuesta

```python
return {
    # ... campos actuales ...
    "cells": cells,
    # Nuevos R3:
    "has_elevation_data": bool(any(c.get("voxel_elevation_masl") is not None for c in cells)),
    "dem_source": metadata.get("dem_source"),
    "georef_confidence": metadata.get("georef_confidence"),
    "elevation_range": {
        "min_voxel_elevation_masl": ...,  # si disponible
        "max_voxel_elevation_masl": ...,
        "surface_elevation_range": {...},
    },
}
```

### 12.3 Compatibilidad hacia atrás

Los campos nuevos son opcionales. Si el parquet no tiene las columnas nuevas (corridas previas a R3), los campos se envían como `None`. El frontend debe manejar `null` para estos campos sin romper.

---

## 13. Frontend plan

### 13.1 Qué cambia en R3 (solo tipos y store en esta fase)

**R3-FE-1 — Tipos nuevos en `frontendApi.ts`:**
```typescript
export type VoxelElevationData = {
  lat: number | null;
  lon: number | null;
  surface_elevation_masl: number | null;
  depth_below_surface_m: number | null;
  voxel_elevation_masl: number | null;
  georef_confidence: string | null;
  dem_source: string | null;
  spatial_reference_warning: string | null;
};

export type TerrainMetadataR3 = {
  // ... todos los campos actuales ...
  min_elevation_m?: number | null;
  max_elevation_m?: number | null;
  mean_elevation_m?: number | null;
  cell_size_x_m?: number;
  cell_size_z_m?: number;
  footprint_source?: string | null;
  georef_confidence?: string;
  terrain_margin_factor?: number;
  warnings?: string[];
};

export type BlockModelMetaR3 = {
  has_elevation_data: boolean;
  dem_source: string | null;
  georef_confidence: string | null;
  elevation_range?: {
    min_voxel_elevation_masl: number | null;
    max_voxel_elevation_masl: number | null;
  };
};
```

**R3-FE-2 — GeoDashboard DEM section:**
- Mostrar: DEM source, georef_confidence del terrain, min/max/mean elevation, terrain_margin_factor
- Si terreno es "mock_v1" o warnings: mostrar badge naranja/rojo
- Si `has_elevation_data = true`: mostrar resumen "Elevación de voxeles disponible"

**R3-FE-3 — Scene3D position logic (después de tener datos R3):**
- Si `voxel_elevation_masl` disponible en celda: usar `voxel_elevation_masl` para posicionar en Y (Three.js)
- Si `voxel_elevation_masl = null`: usar lógica actual (cy = y_center - y_m)
- Scene3D nunca debe inventar elevación — usar null explícitamente como fallback
- Warning en UI si usando fallback: "Posición relativa — elevación absoluta no disponible"

**R3-FE-4 — Host volume DEM plan (solo definición, sin implementar):**
- El host volume actual es un BoxGeometry que envuelve el modelo
- El plan R4: reemplazar con mesh derivado del DEM (top surface = DEM, bottom = min elevation, paredes laterales)
- Para implementarlo, el frontend necesita la DEM matrix completa → nuevo endpoint o incluir en TerrainResponse
- No implementar en R3. Solo actualizar el tipo para preparar la estructura.

**Regla para R3-FE:** Scene3D NO debe calcular física. Si las coordenadas de elevación no vienen del backend, mostrar el modelo en posición relativa con warning visible.

---

## 14. Host volume DEM plan

### 14.1 Situación actual

El host volume visible en la escena 3D es un `BoxGeometry` que envuelve el block model con dimensiones `domainL × domainH × domainW`. Es una caja artificial sin relación con la topografía real.

### 14.2 Plan futuro (R4)

Para un host volume geológicamente honesto:

```
TOP surface    = DEM mesh (topografía real)
BOTTOM surface = plano horizontal a min(voxel_elevation_masl) - depth_margin
SIDE walls     = paredes desde DEM perimeter hacia abajo hasta BOTTOM
```

**Datos necesarios del backend (ya disponibles post-R3):**
- `dem_matrix` 32×32 con georreferenciación (cell_size_x_m, cell_size_z_m, offset del footprint)
- `min_voxel_elevation_masl` del block model
- Footprint corners WGS84 del proyecto

**Implementación R4:**
- Backend: nuevo endpoint `/projects/{id}/terrain-mesh` que retorna lista de triángulos o vértices del DEM
- Frontend: `THREE.BufferGeometry` construido desde los vértices del DEM
- No usar BoxGeometry final

**Por qué no en R3:**
- Requiere cambios no triviales en Scene3D
- Requiere nuevo endpoint
- Depende de que R3-BE-1 a R3-BE-5 estén completos y validados
- El ROI de R3 es establecer la elevación de voxeles; el host volume es visualización avanzada

---

## 15. Tests y QA

### 15.1 Tests automáticos requeridos

```python
# tests/test_r3_terrain_by_footprint.py (NUEVO)

def test_terrain_uses_footprint_when_high_confidence():
    """terrain endpoint usa corners reales si georef_confidence=HIGH."""

def test_terrain_uses_center_fallback_when_low():
    """terrain endpoint usa center+extent si georef_confidence=LOW."""

def test_terrain_warns_when_missing():
    """terrain endpoint retorna warning cuando confidence=MISSING."""

def test_footprint_to_bbox_high_confidence():
    """_footprint_to_bbox con corners reales → bbox correcto con margin 1.5."""

def test_footprint_to_bbox_medium_includes_warning():
    """_footprint_to_bbox confidence=MEDIUM → bbox + warning sobre estimado."""

def test_footprint_to_bbox_missing_returns_none():
    """_footprint_to_bbox sin corners → None bbox + warning."""

def test_terrain_metadata_has_elevation_stats():
    """TerrainResponse.metadata incluye min/max/mean_elevation_m."""

def test_terrain_margin_factor_configurable():
    """terrain_margin_factor afecta el tamaño del DEM bbox."""

# tests/test_r3_dem_sampling.py (NUEVO)

def test_sample_dem_elevation_center_voxel():
    """Voxel en el centro del modelo → sample DEM retorna valor correcto."""

def test_sample_dem_elevation_bilinear():
    """Bilinear interpolation entre celdas DEM."""

def test_sample_dem_elevation_nearest_neighbor():
    """Nearest neighbor cuando method='nearest'."""

def test_sample_dem_elevation_out_of_bounds_clamp():
    """Voxel en borde del DEM → clamp + warning."""

def test_sample_dem_elevation_mock_dem_returns_zero():
    """DEM de ceros → retorna 0.0 + warning 'mock'."""

def test_voxel_absolute_elevation_formula():
    """voxel_elevation_masl = surface_elevation_masl - y_m."""

def test_voxel_elevation_with_depth():
    """Voxel a 5000m de profundidad sobre terreno a 3000m → elevation = -2000m."""

# tests/test_r3_parquet_enrichment.py (NUEVO)

def test_block_model_parquet_gets_elevation_columns():
    """Después de enriquecimiento, parquet tiene columnas nuevas R3."""

def test_block_model_parquet_lat_lon_present_for_utm():
    """Para proyecto UTM+pyproj: lat/lon en parquet son WGS84 válidos."""

def test_block_model_parquet_elevation_none_for_missing_georef():
    """Para confidence=MISSING: elevation cols son None, no error."""

def test_block_model_parquet_depth_below_surface_equals_y_m():
    """depth_below_surface_m = y_m en todos los voxeles."""

# tests/test_r3_block_model_api.py (NUEVO)

def test_block_model_api_returns_elevation_fields():
    """/block-model retorna voxel_elevation_masl cuando disponible."""

def test_block_model_api_has_elevation_data_flag():
    """/block-model retorna has_elevation_data=True si parquet enriquecido."""

def test_block_model_api_null_elevation_for_old_runs():
    """/block-model retorna null elevation para runs pre-R3."""

# tests/test_r3_terrain_persistence.py (NUEVO)

def test_terrain_metadata_saved_on_request():
    """terrain endpoint guarda terrain_metadata.json en directorio del proyecto."""

def test_terrain_metadata_loadable_for_enrichment():
    """Metadata guardada es legible y tiene todos los campos para R3-BE-4."""

# tests/test_r1_r2_no_regression.py (verificar regresión — NO MODIFICAR)
# Ejecutar como parte del CI de R3:
#   python -m pytest tests/test_r1_*.py tests/test_r2_*.py -v
```

### 15.2 QA manual requerido

**QA-R3-1: Terrain por footprint real**
- Dataset: CSV UTM 19S con pyproj funcionando (`georef_confidence = HIGH`)
- Acción: `GET /projects/{id}/terrain`
- Expectativa: bbox del terrain cubre exactamente el footprint × 1.5; metadata incluye min/max elevation

**QA-R3-2: Terrain fallback por baja confianza**
- Dataset: HVC CSV local_meters con ancla Atacama (`georef_confidence = LOW`)
- Acción: `GET /projects/{id}/terrain`
- Expectativa: terreno calculado con center+extent, warning "solo contexto visual"

**QA-R3-3: Terrain sin georreferenciación**
- Dataset: CSV sin lat/lon (`georef_confidence = MISSING`)
- Acción: `GET /projects/{id}/terrain`
- Expectativa: HTTP 404 o respuesta con warnings fuertes, NO terreno en posición errónea

**QA-R3-4: sample_dem_elevation manual**
- Usar DEM sintético 4×4 con valores conocidos
- Verificar bilinear interpolation en posiciones intermedias
- Verificar clamp en bordes

**QA-R3-5: Enriquecimiento parquet**
- Ejecutar inversión completa (LSQR) → parquet base
- Ejecutar enriquecimiento R3 → verificar columnas nuevas
- Verificar: `depth_below_surface_m = y_m` para todos los voxeles
- Verificar: `voxel_elevation_masl` decrece con profundidad

**QA-R3-6: /block-model expone elevation**
- `GET /block-model?project_id=X&run_id=Y`
- Verificar: response tiene `has_elevation_data=true`
- Verificar: celdas tienen `voxel_elevation_masl` no null
- Verificar: `has_elevation_data=false` para runs anteriores a R3

**QA-R3-7: No-regresión R1/R2**
- Ejecutar suite completa de tests R1 y R2
- Verificar: ningún test existente rompe con cambios R3

---

## 16. Riesgos

| # | Riesgo | Probabilidad | Impacto | Mitigación |
|---|--------|-------------|---------|------------|
| 1 | **GEE unavailable** — el terrain endpoint no puede consultar GLO-30 | MEDIA | ALTO | Fallback a `mock_v1` (matriz de ceros) + warning prominente. R3 continúa sin elevación real. |
| 2 | **DEM resolution coarse** — 32×32 sobre 50km = 1562m/celda → grueso para voxeles de 1557m | MEDIA | MEDIA | Para HVC es barely suficiente. Para surveys más pequeños, aumentar DEM_RESOLUTION a 64 en R3-BE-1. |
| 3 | **DEM bbox mismatch** — el footprint pyproj y el DEM tienen CRS distintos | BAJA | ALTO | Verificar: footprint en WGS84, DEM en EPSG:4326 (= WGS84). El GLO-30 se retorna en EPSG:4326. Sin problema. |
| 4 | **Modelo x/z orientación mismatch** — el eje X del modelo puede no ser exactamente E-O | MEDIA | ALTO | El documento R2 dice que `_utm_to_local_meters()` hace shift SW. Si el survey tiene rotación, la correspondencia x_m→E-O no es exacta. R3 asume ejes alineados. Warning en documentación. |
| 5 | **local_meters sin orientación real** — x_m=0 no es necesariamente el borde W | ALTA (para HVC) | MEDIA | Para `confidence=LOW`, la correspondencia voxel→lat/lon es aproximada. Warning en parquet. |
| 6 | **UTM wrong zone** — zona declarada incorrecta → offset de 500km | MEDIA | ALTO | Mitigación R2: validate_utm_easting_northing. R3 hereda: si crs_confidence=LOW, no calcular lat/lon pyproj. |
| 7 | **Terrain margin too small** — voxel en borde del modelo fuera del DEM | BAJA | MEDIA | margin_factor=1.5 previene este caso. Verificación explícita en R3-BE-4. |
| 8 | **Storing huge DEM matrix** — para surveys grandes, DEM más denso → JSON grande | BAJA | BAJA | 32×32 = 1024 floats ≈ 8KB. Si se aumenta a 64×64 = 4096 floats ≈ 32KB. Acceptable. Si se aumenta a 256×256 → ~500KB → usar archivo binario. |
| 9 | **Frontend performance** — enviar elevation_masl para 5000 voxeles añade ~40KB | BAJA | BAJA | 5000 voxeles × 3 floats × 8 bytes ≈ 120KB. Acceptable para web. |
| 10 | **Consistencia parquet multi-run** — runs antiguos sin elevation, runs nuevos con elevation | ALTA | MEDIA | El frontend debe manejar `null` para todos los campos de elevación. `has_elevation_data` flag comunica esto. |
| 11 | **pyproj no disponible en producción** — si Docker no tiene pyproj | BAJA | ALTO | R2.3 verifica que pyproj está instalado. Pero agregar test de smoke en R3-QA. |
| 12 | **Discrepancia DEM vs profundidad del modelo** — modelo llega a -30km pero DEM solo da altitud superficial | NINGUNO | BAJO | Por definición, `voxel_elevation_masl = surface_elevation - depth`. Profundidades > surface_elevation dan elevaciones negativas. Correcto. |

---

## 17. Plan de ejecución por subfases

### Orden recomendado

```
R3-BE-1 — Terrain endpoint by footprint real
  Archivos: satellite_service.py, terrain_schema.py, terrain_api.py
  Tiempo: 90 min
  Prerequisito: R2.3 PASS (pyproj funcionando)
  Resultado: terrain usa corners reales cuando confidence ≥ MEDIUM

R3-BE-2 — DEM sampling utilities
  Archivos: core/geo_utils.py o services/terrain_sampling_service.py (nuevo)
  Tiempo: 60-90 min
  Prerequisito: R3-BE-1 completado
  Resultado: sample_dem_elevation() funciona con tests

R3-BE-3 — Persist DEM metadata
  Archivos: satellite_service.py, core/block_model_store.py
  Tiempo: 45 min
  Prerequisito: R3-BE-1 completado
  Resultado: terrain_metadata.json se guarda por proyecto

R3-BE-4 — Enrich block_model.parquet
  Archivos: services/block_model_service.py o nuevo services/block_model_enrichment_service.py
  Tiempo: 90-120 min
  Prerequisito: R3-BE-2 + R3-BE-3
  Resultado: parquet tiene columnas elevation, lat, lon, depth_below_surface_m

R3-BE-5 — Block model API exposes elevation fields
  Archivos: services/block_model_service.py, api/block_model_api.py
  Tiempo: 45 min
  Prerequisito: R3-BE-4
  Resultado: /block-model retorna campos nuevos en cells[]

R3-FE-1 — Types/store update
  Archivos: frontendApi.ts, useAppStore.ts
  Tiempo: 30 min
  Prerequisito: R3-BE-5 completado
  Resultado: tipos TypeScript para campos R3

R3-FE-2 — GeoDashboard DEM section
  Archivos: componentes/huds/GeoDashboard.tsx
  Tiempo: 45 min
  Prerequisito: R3-FE-1
  Resultado: DEM source, elevation stats en el HUD

R3-FE-3 — Scene3D position logic (opcional, depende de validación visual)
  Archivos: componentes/Scene3D.tsx, componentes/views/Exploration3DView.tsx
  Tiempo: 60-90 min
  Prerequisito: R3-FE-2 + QA-R3-5 PASS
  Resultado: voxeles posicionados con elevation real si disponible

R3-QA — End-to-end
  Tiempo: 1 día
  Prerequisito: R3-FE-1 completado mínimo
  Resultado: QA-R3-1 a QA-R3-7 documentados
```

### Criterio de cierre de R3

- [ ] `GET /projects/{id}/terrain` usa footprint corners cuando `georef_confidence ≥ MEDIUM`
- [ ] `TerrainMetadata` incluye `min_elevation_m`, `max_elevation_m`, `mean_elevation_m`, `cell_size_x_m`, `cell_size_z_m`, `georef_confidence`, `warnings`
- [ ] `terrain_metadata.json` se guarda en el directorio del proyecto
- [ ] `sample_dem_elevation()` pasa tests bilinear + nearest + out-of-bounds
- [ ] `block_model.parquet` tiene columnas `surface_elevation_masl`, `depth_below_surface_m`, `voxel_elevation_masl` después del enriquecimiento
- [ ] `/block-model` retorna `has_elevation_data` y campos de elevation en celdas
- [ ] Para confidence = LOW/MISSING: campos elevation son `null`, no error
- [ ] Suite completa de tests R1/R2 no rompe
- [ ] `cmd /c npm run lint` pasa sin errores
- [ ] `python -m pytest tests/ -v` pasa incluyendo tests R3 nuevos

---

## 18. Prompts de ejecución sugeridos

### Prompt R3-BE-1 — Terrain endpoint by footprint real

```
Rol: Arquitecto backend Python/FastAPI. TerraQuantum.

Contexto:
- R2.3 está completado. pyproj funciona. project_meta.json tiene footprint con source="utm_pyproj"
  y corners WGS84 reales (confidence="HIGH").
- terrain_api.py: GET /projects/{id}/terrain → get_terrain_data(project_id).
- satellite_service.py: get_terrain_data() usa solo center_lat/lon + extent + buffer=20%.
  No lee el project_footprint. No usa los corners reales.
- terrain_schema.py: TerrainMetadata no tiene min/max/mean elevation ni cell sizes en metros.

Tarea: Modificar terrain endpoint para usar footprint real cuando confidence ≥ MEDIUM.

Archivos permitidos:
- terraquantum-backend/services/satellite_service.py
- terraquantum-backend/schemas/terrain_schema.py

Archivos prohibidos: NO tocar terrain_api.py. NO tocar block_model_service.py. NO tocar el solver.

Cambios exactos:

1. En terrain_schema.py, agregar campos opcionales a TerrainMetadata:
   - min_elevation_m: Optional[float] = None
   - max_elevation_m: Optional[float] = None
   - mean_elevation_m: Optional[float] = None
   - cell_size_x_m: float = 0.0
   - cell_size_z_m: float = 0.0
   - footprint_source: Optional[str] = None
   - georef_confidence: str = "MISSING"
   - terrain_margin_factor: float = 1.5
   - warnings: List[str] = Field(default_factory=list)

2. En satellite_service.py:
   a. Agregar constante: TERRAIN_MARGIN_FACTOR = 1.5
   b. Agregar función _footprint_to_bbox(footprint: dict, margin_factor: float) -> tuple[dict | None, list[str]]:
      - Si confidence en ("HIGH", "MEDIUM") y sw/ne tienen lat/lon válidos:
        → calcular bbox con margin_factor sobre los corners reales
        → MEDIUM agrega warning "Footprint estimado"
      - Si confidence LOW/MISSING:
        → retornar None, [warning "solo contexto visual"]
   c. Modificar get_terrain_data(project_id) para:
      - Leer project_meta completo (ya lo hace via _read_project_center, extender para leer footprint)
      - Si footprint existe y confidence ≥ MEDIUM: usar _footprint_to_bbox()
      - Si bbox es None o fallback: usar compute_bbox() con center+extent (método actual)
      - Después de obtener dem_matrix de GEE: calcular min/max/mean elevation del array
      - Calcular cell_size_x_m y cell_size_z_m desde bbox y DEM_ROWS/DEM_COLS
      - Retornar TerrainMetadata con todos los campos nuevos poblados

Validación:
- python -m compileall services/satellite_service.py schemas/terrain_schema.py
- Para proyecto con confidence=HIGH: verify bbox usa corners reales (no center+extent)
- Para proyecto con confidence=LOW: verify bbox usa center+extent con warning

Respuesta final obligatoria:
1. Archivos modificados.
2. Cambios exactos por archivo.
3. Compilación → resultado.
4. Qué NO se tocó.
5. Riesgos pendientes.
```

---

### Prompt R3-BE-2 — DEM sampling utilities

```
Rol: Arquitecto backend Python/FastAPI. TerraQuantum.

Contexto:
- R3-BE-1 completado. TerrainMetadata tiene cell_size_x_m, cell_size_z_m y bbox extendido.
- El block model tiene voxeles en coordenadas locales (x_m, z_m) ∈ [0, extent_x_m] × [0, extent_z_m].
- El DEM es una matriz 32×32 que cubre un bbox más grande que el modelo (margin_factor=1.5).
- Necesitamos una función que mapee (x_m, z_m) del voxel → índice en la DEM matrix → elevación interpolada.

Tarea: Implementar sample_dem_elevation() en core/geo_utils.py.

Archivos permitidos:
- terraquantum-backend/core/geo_utils.py

Archivos prohibidos: NO tocar otros archivos.

Cambios exactos:

Agregar función sample_dem_elevation al final de core/geo_utils.py:

def sample_dem_elevation(
    dem_matrix: list[list[float]],
    dem_metadata: dict,
    x_m: float,
    z_m: float,
    model_extent_x_m: float,
    model_extent_z_m: float,
    method: str = "bilinear",
) -> tuple[float, str]:
    """
    Muestrea elevación del DEM en posición local (x_m, z_m) del modelo.
    
    dem_metadata debe tener: bbox (min_lat, max_lat, min_lon, max_lon),
    dem_rows, dem_cols, model_sw_lat, model_sw_lon (lat/lon del borde SW del modelo).
    
    Returns: (elevation_masl, warning_str) donde warning_str="" si OK.
    """
    
    Lógica:
    1. Calcular bbox_x_m y bbox_z_m desde dem_metadata.bbox y METERS_PER_DEG_LAT
    2. Calcular offset: posición del SW del modelo dentro del DEM bbox en metros
       (usando model_sw_lat/lon si disponibles, o footprint corners)
    3. Calcular posición fraccionaria en el DEM:
       col_f = (offset_x_m + x_m) / bbox_x_m * dem_cols
       row_f = (bbox_z_m - offset_z_m - z_m) / bbox_z_m * dem_rows  ← invertir (row 0 = norte)
    4. Clamp a [0, dem_rows-1] y [0, dem_cols-1] con warning si fue necesario
    5. Si method="bilinear": bilinear interpolation entre 4 celdas vecinas
       Si method="nearest": round a índice entero
    6. Retornar (elevacion, warning)
    
    Casos especiales:
    - Si dem_matrix está vacío: retornar (0.0, "DEM vacío")
    - Si dem_matrix todos ceros: retornar (0.0, "DEM mock — elevación conceptual")
    - Si out_of_bounds después de clamp: agregar warning "voxel fuera del DEM bbox"

Agregar también _bilinear_interp(matrix, row_f, col_f) → float como función privada.

Validación:
- python -m compileall core/geo_utils.py
- Tests manuales:
  DEM 4×4 con valores conocidos → bilinear center → valor esperado
  row_f=0.5, col_f=0.5 → promedio de las 4 celdas centrales

Respuesta final obligatoria:
1. Código exacto de sample_dem_elevation().
2. Código exacto de _bilinear_interp().
3. Compilación.
4. 3 casos de prueba manuales con resultado.
5. Qué NO se tocó.
6. Riesgos.
```

---

### Prompt R3-BE-3 — Persist DEM metadata

```
Rol: Arquitecto backend Python/FastAPI. TerraQuantum.

Contexto:
- R3-BE-1 completado. TerrainMetadata extendida está disponible.
- terrain_metadata.json debe guardarse en data/projects/{project_id}/
- block_model_store.py tiene save_project_meta() y load_project_meta() como referencias de patrón.

Tarea: Persistir terrain_metadata.json en directorio del proyecto.

Archivos permitidos:
- terraquantum-backend/services/satellite_service.py
- terraquantum-backend/core/block_model_store.py

Archivos prohibidos: NO tocar schemas. NO tocar terrain_api.py. NO tocar solver.

Cambios exactos:

1. En block_model_store.py:
   Agregar constante: PROJECT_TERRAIN_METADATA_FILENAME = "terrain_metadata.json"
   Agregar función save_terrain_metadata(project_id: str, metadata: dict) -> None
   (mismo patrón que save_project_meta — escribir JSON a {project_dir}/terrain_metadata.json)
   Agregar función load_terrain_metadata(project_id: str) -> Optional[dict]
   (mismo patrón que load_project_meta)

2. En satellite_service.py:
   Al final de get_terrain_data(), antes del return:
   - Construir dict de metadata con todos los campos (bbox, cell_sizes, elevation stats, footprint_source, etc.)
   - Llamar save_terrain_metadata(clean_project_id, terrain_metadata_dict)
   - Si falla el save: solo loguear warning, no lanzar excepción (el terrain response es lo principal)

Validación:
- python -m compileall services/satellite_service.py core/block_model_store.py
- Después de llamar GET /projects/{id}/terrain: verificar que terrain_metadata.json existe
- Verificar que terrain_metadata.json es JSON válido con campos bbox, min_elevation_m, etc.

Respuesta final obligatoria:
1. Archivos modificados.
2. Cambios exactos.
3. Compilación.
4. Prueba manual de persistencia.
5. Qué NO se tocó.
6. Riesgos.
```

---

### Prompt R3-BE-4 — Enrich block_model.parquet

```
Rol: Arquitecto backend Python/FastAPI. TerraQuantum.

Contexto:
- R3-BE-1/2/3 completados.
- block_model.parquet existe en el run dir. Tiene ix, iy, iz, x, y, z, density.
- y_m es profundidad positiva hacia abajo (confirmado en block_model_service.py).
- terrain_metadata.json existe en el project dir.
- terrain_dem_matrix.json puede existir (si se implementó en R3-BE-3).
- coordinate_transform_real.py tiene transform_utm_to_wgs84() con pyproj.
- gravity_import_metadata.json tiene coordinate_transform con x_min_raw, z_min_raw.

Tarea: Crear servicio de enriquecimiento del parquet con columnas de elevación.

Archivos permitidos:
- terraquantum-backend/services/block_model_enrichment_service.py (NUEVO)
- terraquantum-backend/core/geo_utils.py (solo para importar sample_dem_elevation)

Archivos prohibidos: NO tocar block_model_service.py directamente.
NO tocar el solver. NO tocar gravity_import_api.py.

Crear services/block_model_enrichment_service.py con:

def enrich_block_model_with_elevation(
    project_id: str,
    run_id: str,
) -> dict:
    """
    Lee block_model.parquet, agrega columnas de elevación, sobreescribe el parquet.
    
    Returns: {
        "status": "ok" | "skipped" | "error",
        "voxels_enriched": int,
        "columns_added": [str],
        "warnings": [str],
        "error": str | None,
    }
    """
    
    Lógica:
    1. Cargar block_model.parquet con polars
    2. Cargar terrain_metadata.json (si existe)
    3. Cargar inputs.json del run → block_size_m
    4. Cargar gravity_import_metadata.json → x_min_raw, z_min_raw (offset UTM)
    5. Cargar project_meta.json → georef_confidence, epsg_code, utm_zone
    6. Para cada voxel (fila del df):
       a. depth_below_surface_m = y_m  (positiva hacia abajo — sin cambio)
       b. surface_elevation_masl = sample_dem_elevation(dem_matrix, dem_metadata, x_m, z_m, ...)
          Si dem_matrix no disponible: surface_elevation_masl = None
       c. voxel_elevation_masl = surface_elevation_masl - depth_below_surface_m
          Si surface_elevation_masl is None: voxel_elevation_masl = None
       d. lat, lon: si epsg_code y crs_confidence ≥ MEDIUM y x_min_raw disponible:
          easting = x_min_raw + x_m
          northing = z_min_raw + z_m
          lat, lon = transform_utm_to_wgs84(easting, northing, epsg_code=epsg_code)
          Si falla o confianza baja: lat=None, lon=None
    7. Agregar columnas con polars (vectorized si posible)
    8. Sobreescribir block_model.parquet con las columnas nuevas
    9. No tocar block_model_anomaly.parquet ni block_model_focusing.parquet aquí

Validación:
- python -m compileall services/block_model_enrichment_service.py
- Ejecutar enriquecimiento en un run real: verificar columnas presentes en parquet
- Verificar: depth_below_surface_m = y_m para todos los voxeles
- Verificar: voxel_elevation_masl decrece con profundidad (mayor y_m → menor elevation)

Respuesta final obligatoria:
1. Archivo creado.
2. Lógica exacta implementada.
3. Compilación.
4. Prueba con run real.
5. Qué NO se tocó.
6. Riesgos.
```

---

### Prompt R3-FE-1 — Types/store update

```
Rol: Arquitecto frontend React/TypeScript/Next.js. TerraQuantum.

Contexto:
- R3 backend completado. /block-model retorna campos nuevos de elevación.
- frontendApi.ts tiene tipos R1/R2. No tiene tipos para elevation.
- useAppStore.ts tiene projectFootprint, georefConfidence, crsInfo.

Tarea: Agregar tipos R3 y campos de store.

Archivos permitidos:
- terraquantum-web/lib/terraquantum/frontendApi.ts
- terraquantum-web/store/useAppStore.ts

Archivos prohibidos: NO tocar componentes. NO tocar Scene3D.

Cambios en frontendApi.ts:
1. Agregar tipo VoxelElevationData con:
   lat, lon, surface_elevation_masl, depth_below_surface_m, voxel_elevation_masl,
   georef_confidence, dem_source, spatial_reference_warning (todos opcional/null)

2. Agregar tipo TerrainMetadataR3 extendiendo los campos actuales de TerrainMetadata con:
   min_elevation_m, max_elevation_m, mean_elevation_m, cell_size_x_m, cell_size_z_m,
   footprint_source, georef_confidence, terrain_margin_factor, warnings

3. Agregar tipo BlockModelElevationMeta con:
   has_elevation_data: boolean
   dem_source: string | null
   georef_confidence: string | null
   elevation_range?: { min_voxel_elevation_masl: number | null; max_voxel_elevation_masl: number | null }

Cambios en useAppStore.ts:
1. Agregar campo: hasElevationData: boolean (default false)
2. Agregar campo: demSource: string | null
3. Agregar campo: elevationRange: { min: number | null; max: number | null } | null
4. Agregar acciones: setHasElevationData, setDemSource, setElevationRange
5. Limpiar estos campos cuando se resetea activeRun

Validación:
- cmd /c npx eslint lib/terraquantum/frontendApi.ts store/useAppStore.ts
- Sin errores TypeScript.

Respuesta final obligatoria:
1. Archivos modificados.
2. Tipos agregados: lista exacta.
3. Campos de store agregados.
4. ESLint resultado.
5. Qué NO se tocó.
6. Riesgos.
```

---

### Prompt R3-QA — End-to-end

```
Rol: QA engineer de TerraQuantum. R3 backend y frontend completados.

Contexto:
- Backend corriendo en localhost:8010
- Frontend corriendo en localhost:3000
- R3-BE-1 a R3-BE-5 completados
- R3-FE-1 a R3-FE-2 completados mínimo

Tarea: Ejecutar QA manual de R3 con los 7 casos definidos.

NO modificar ningún archivo. Solo observar, verificar y reportar.

Casos a verificar (ver Sección 15.2 del spec R3):
QA-R3-1: Terrain por footprint real → bbox usa corners × 1.5
QA-R3-2: Terrain fallback LOW → warning "solo contexto visual"
QA-R3-3: Terrain MISSING → no retorna terreno erróneo
QA-R3-4: sample_dem_elevation manual → bilinear correcto
QA-R3-5: Enriquecimiento parquet → columnas presentes, depth=y_m
QA-R3-6: /block-model expone elevation → has_elevation_data=true
QA-R3-7: No-regresión R1/R2 → python -m pytest tests/test_r1_*.py tests/test_r2_*.py -v PASS

Para cada caso:
1. Ejecutar acción exacta.
2. Verificar resultado campo por campo.
3. Reportar PASS o FAIL con evidencia.

Respuesta final obligatoria:
1. QA-R3-1 a QA-R3-7: PASS/FAIL + evidencia.
2. Tests automáticos R1/R2 → resultado.
3. Tests automáticos R3 → resultado.
4. Confirmación de que NO se modificó ningún archivo.
5. FAILs documentados con paso de reproducción exacto.
```

---

*Fin de la especificación R3.*

*Este documento NO reemplaza R1_SPATIAL_CONTRACT_SPEC.md, R2_CRS_UTM_PYPROJ_SPEC.md ni la INDUSTRIAL_REALITY_BIBLE.md — los complementa para la fase R3.*  
*Próxima fase: R4 — Host volume DEM mesh, slices profesionales con profundidad real, colorbar técnica.*
