# TERRAQUANTUM — R1 SPATIAL CONTRACT SPEC
## Contrato espacial real: footprint, CRS, georef_confidence y verdad geográfica

**Versión:** 1.0  
**Fecha:** 2026-05-19  
**Autor:** Claude Code — Auditoría completa de código fuente + diseño arquitectónico  
**Estado:** ESPECIFICACIÓN EJECUTABLE — ACTIVA  
**Fuentes:** Código fuente auditado en solo lectura. Documentos de referencia consultados. Ver Sección 2.

---

> **Propósito de este documento:**  
> Especificación técnica completa y ejecutable para implementar R1 — Contrato espacial real. Define qué existe, qué falta, qué cambiar, en qué orden, y cómo validar. No es una explicación vaga. Cada sección termina en criterios de aceptación concretos.

---

## 1. Dictamen R1

### 1.1 Veredicto técnico

TerraQuantum tiene la infraestructura de schemas para georreferenciación, pero la cadena completa está incompleta: schemas definidos, lógica de clasificación implementada, pero no expuesta correctamente en endpoints, no incluida en el reporte HTML, y completamente ausente del frontend.

**Lo que ya existe (sorpresa positiva):**
- `ProjectFootprint` y `ProjectFootprintCorner` están definidos en `project_schema.py`.
- `georef_confidence` existe en `ProjectMeta` y `ProjectResponse` como campo.
- `_classify_georef()` existe en `gravity_import_api.py` y clasifica `HIGH/MEDIUM/LOW/MISSING`.
- `compute_footprint_from_center()` existe en `core/geo_utils.py` y calcula 4 esquinas.
- El footprint se persiste en `project_meta.json` durante `/invert` cuando `x_extent_m > 0`.

**Lo que no existe o está incompleto:**
- No hay endpoint dedicado `GET /projects/{project_id}/footprint`.
- `build_project_response()` en `project_api.py` no popula `georef_confidence` ni `footprint`.
- El preview endpoint no llama a `_classify_georef()`.
- El reporte HTML no tiene sección de georreferenciación.
- El frontend no consume ni muestra `georef_confidence` ni `footprint` en ningún lugar.
- No se detecta ni almacena zona UTM.
- `pyproj` no está instalado — solo aproximación equirectangular.
- Los voxels no tienen coordenadas absolutas ni elevación referenciada al DEM.

### 1.2 Decisión principal de R1

R1 completa la cadena que ya está parcialmente construida. No reescribe lo que existe. Conecta los eslabones rotos.

R1 NO implementa:
- Zona UTM automática (se documenta el faltante con warning, no se bloquea el flujo).
- Coordenadas absolutas en voxels (eso es R3).
- DEM co-registrado con footprint (eso es R3).
- `pyproj` (se decide en esta fase cuándo agregarlo — ver Sección 14).
- Cambios en `Scene3D.tsx` o visualización 3D.

---

## 2. Estado actual de georreferenciación

### 2.1 Respuestas a las preguntas de auditoría

**A1. ¿Dónde se guarda hoy `latitude` y `longitude`?**

En tres lugares:
1. `project_meta.json` → campos `latitude`, `longitude` (floats o null).
2. `gravity_import_metadata.json` → campos `lat`, `lon`, `latitude`, `longitude` (redundancia intencional para trazabilidad).
3. `inputs.json` → campos `lat`, `lon` como strings (pasados al solver geofísico).

**NO** en `block_model.parquet` ni en ningún archivo de modelo 3D.

**A2. ¿Dónde se crea `project_meta.json`?**

Dos rutas:
- `gravity_import_api.py` línea ~324: durante `/invert`, SOLO si `project_meta_path` no existe y lat/lon son válidos.
- `project_api.py` línea ~83: durante `POST /projects` (creación explícita de proyecto). En este caso, `georef_confidence` queda en `"LOW"` por defecto y `footprint` queda `null`.

**Riesgo activo:** Si el proyecto se crea vía `POST /projects` antes de `/invert`, el `project_meta.json` tiene `georef_confidence="LOW"` y `footprint=null` sin importar el CSV posterior.

**A3. ¿Qué campos tiene hoy `project_meta.json`?**

Cuando se crea desde `/invert` (path completo):
```json
{
  "project_id": "string",
  "latitude": -22.28,
  "longitude": -68.89,
  "crs": "EPSG:4326",
  "created_at": "2026-05-18T07:24:34Z",
  "updated_at": "2026-05-18T07:24:34Z",
  "source": "csv_import",
  "georef_confidence": "HIGH|MEDIUM|LOW|MISSING",
  "georef_type": "latlon|csv_utm|local_meters_anchored|derived|local_reference",
  "footprint": {
    "crs": "EPSG:4326",
    "type": "bbox",
    "source": "georef_type_value",
    "confidence": "HIGH|MEDIUM|LOW|MISSING",
    "sw": {"lat": float, "lon": float},
    "se": {"lat": float, "lon": float},
    "ne": {"lat": float, "lon": float},
    "nw": {"lat": float, "lon": float},
    "warnings": ["string"]
  }
}
```

Cuando se crea desde `POST /projects` (campos por defecto de `ProjectMeta`):
```json
{
  "project_id": "string",
  "latitude": null,
  "longitude": null,
  "crs": "EPSG:4326",
  "created_at": "...",
  "updated_at": "...",
  "georef_confidence": "LOW",
  "footprint": null
}
```

**A4. ¿Qué detecta exactamente `coordinate_transform_service.py`?**

La función `transform_coordinates()` detecta:
- Sistema de coordenadas: `latlon`, `utm`, `local_meters`, o `identity_fallback` (low confidence).
- Extents (`x_extent_m`, `z_extent_m`) en metros.
- Bounding box raw (`x_min_raw`, `x_max_raw`, `z_min_raw`, `z_max_raw`).
- Método de transformación aplicado.
- Warnings (ej. si extent > 100 km en el caso lat/lon).

**No detecta:** zona UTM, hemisferio, EPSG code real para UTM, orientación del survey, elevación.

**A5. ¿Qué significa hoy `local_meters`?**

Coordenadas en metros locales (x_m, z_m) sin referencia geográfica absoluta. El origen es la esquina SW del bounding box. La orientación del eje x (Este) y z (Norte) se asume por convención, no se verifica. No hay transformación a coordenadas geográficas absolutas.

**A6. ¿Cómo se maneja UTM hoy?**

`_utm_to_local_meters()` hace SOLO normalización al origen SW (easting_min, northing_min como offset). NO reproyecta a WGS84. NO identifica qué zona UTM es. Produce `precision_note: "No se realizo reproyeccion geografica. Solo normalizacion de origen local."`.

**Consecuencia:** Un CSV con coordenadas UTM zona 19S y un CSV con UTM zona 33N se procesan de forma idéntica internamente. El sistema no puede distinguirlos.

**A7. ¿Se guarda zona UTM?**

No. Ningún campo en ningún schema registra la zona UTM. El campo `crs` siempre queda como `"EPSG:4326"` incluso cuando el CSV tiene coordenadas UTM.

**A8. ¿Se guarda CRS real o solo `EPSG:4326`?**

Solo `"EPSG:4326"` como string hardcodeado en todos los casos. Para un CSV con coordenadas UTM, el CRS guardado es `"EPSG:4326"` aunque los datos sean `EPSG:32619` (UTM zona 19N). Esto es semánticamente incorrecto.

**A9. ¿Existe `ProjectFootprint` ya?**

Sí. Definido en `terraquantum-backend/schemas/project_schema.py`:
```python
class ProjectFootprintCorner(BaseModel):
    lat: Optional[float] = None
    lon: Optional[float] = None

class ProjectFootprint(BaseModel):
    crs: str = "EPSG:4326"
    type: str = "missing"   # "bbox" | "polygon" | "local_reference" | "missing"
    sw: ProjectFootprintCorner
    se: ProjectFootprintCorner
    ne: ProjectFootprintCorner
    nw: ProjectFootprintCorner
    source: str = "missing"  # "latlon" | "csv_utm" | "local_meters_anchored" | "derived" | "missing"
    confidence: str = "MISSING"  # "HIGH" | "MEDIUM" | "LOW" | "MISSING"
    warnings: List[str]
```

**A10. ¿Existe `georef_confidence` ya?**

Sí. En tres lugares:
1. `ProjectMeta.georef_confidence: str = "LOW"` (schema).
2. `ProjectResponse.georef_confidence: str = "LOW"` (schema).
3. `_classify_georef()` en `gravity_import_api.py` — función que calcula la confianza real.

**Problema:** `build_project_response()` en `project_api.py` NO lee `georef_confidence` del `project_meta.json` al construir `ProjectResponse`. La función retorna un `ProjectResponse` sin poblar `georef_confidence` ni `footprint` desde el meta.

**A11. ¿Existe endpoint `/project-footprint`?**

No. Los endpoints disponibles son:
- `GET /projects/{project_id}` → retorna `ProjectResponse` con `footprint: null` (no se popula).
- `GET /projects` → lista proyectos sin footprint.
- `POST /projects`, `PATCH /projects/{project_id}` → no retornan footprint.

No existe `GET /projects/{project_id}/footprint` ni `/project-footprint`.

**A12. ¿El endpoint terrain usa punto central, bbox o polygon?**

Punto central. `satellite_service._read_project_center()` lee `latitude/longitude` del `project_meta.json`. Luego `_latest_source_gravity_csv()` deriva extents del CSV si está disponible. `compute_bbox()` con buffer 20% calcula el área de terreno. El bbox resultante NO es el `ProjectFootprint` — es un cálculo separado con buffer propio.

**A13. ¿El CSV preview ya puede mostrar confianza de georreferenciación?**

No. El endpoint `/preview` en `gravity_import_api.py` NO llama a `_classify_georef()`. El response del preview incluye `coordinate_transform` (que tiene el sistema detectado y warnings), pero no calcula ni expone `georef_confidence` ni un footprint.

**A14. ¿El report HTML ya tiene sección de georreferenciación real?**

No. `report_generator.py` lee `inputs.json`, `report.json`, `metrics.json` y `favorability.json`. No lee `project_meta.json`. El HTML no contiene ninguna sección de footprint, zona UTM, CRS, ni nivel de confianza de georreferenciación.

**A15. ¿Los voxels tienen lat/lon absoluta?**

No. `block_model.parquet` contiene columnas `cx` (x en metros locales), `cy` (profundidad en metros), `cz` (z en metros locales), `density`, y derivadas (grade, anomaly score, etc.). No hay columnas `lat`, `lon`, `easting`, `northing`, ni `elevation_masl`.

**A16. ¿Los voxels tienen elevación absoluta?**

No. La profundidad `cy` es desde la superficie modelada (y=0 = superficie del survey), no referenciada al DEM real georreferenciado.

**A17. ¿El `block_model.parquet` tiene columnas geoespaciales?**

No. Las columnas son locales, no georreferenciadas.

---

### 2.2 Documentos auditados

| Documento | Estado |
|-----------|--------|
| `docs/TERRAQUANTUM_INDUSTRIAL_REALITY_BIBLE.md` | EXISTE — v1.1 post-C5, leído |
| `docs/TERRAQUANTUM_DEFINITIVE_EXECUTION_PLAN.md` | EXISTE — leído |
| `docs/TERRAQUANTUM_GEOSPATIAL_3D_CORE_STRATEGY.md` | EXISTE — leído |
| `docs/TERRAQUANTUM_HVC_VALIDATION_V1.md` | EXISTE — leído |
| `README.md` | Estado no verificado en esta sesión |
| `README_TERRAQUANTUM_LOCAL.md` | Estado no verificado |
| `README_TERRAQUANTUM_DOCKER.md` | Estado no verificado |
| `terraquantum-backend/README.md` | Estado no verificado |
| `terraquantum-web/README.md` | Estado no verificado |

---

## 3. Problema que R1 resuelve y problema que R1 NO resuelve

### 3.1 Lo que R1 resuelve

R1 resuelve la **cadena de exposición del contrato espacial**: los schemas existen, la lógica de clasificación existe, el footprint se persiste. Pero nada de eso llega al endpoint, al reporte, ni al frontend. R1 conecta esos eslabones.

Específicamente:

1. **Exposición en endpoint:** `GET /projects/{project_id}/footprint` retorna el footprint con toda su metadata.
2. **Exposición en response de invert:** el response de `/invert` ya incluye `georef_confidence` y `footprint` en el cuerpo de respuesta.
3. **Exposición en preview:** `/preview` calcula y retorna `georef_confidence` y tipo de footprint (sin persisitir).
4. **Exposición en `GET /projects/{project_id}`:** `build_project_response` popula correctamente `georef_confidence` y `footprint` desde `project_meta.json`.
5. **Georef en reporte HTML:** sección de georreferenciación en el HTML exportable.
6. **Zona UTM como campo de meta:** aunque no se reproyecta, se registra que la zona es desconocida como warning explícito.
7. **Frontend: badge de confianza:** el frontend muestra un badge de color según el nivel de confianza.
8. **Frontend: footprint type visible:** el frontend muestra el tipo de footprint y sus warnings.
9. **Frontend: honestidad en UX copy:** el texto de UI es honesto sobre qué significa cada nivel de confianza.

### 3.2 Lo que R1 NO resuelve

R1 no es R3. Los siguientes problemas quedan para R3:

| Problema | Fase correcta |
|----------|---------------|
| Coordenadas absolutas de voxels (lat/lon por voxel) | R3 |
| Elevación absoluta de voxels referenciada al DEM | R3 |
| Host volume siguiendo topografía DEM | R3 |
| Terreno GEE por bbox real del footprint (en lugar de punto central) | R3 |
| Reproyección UTM real con pyproj (si se decide instalar) | R2 o R3 |
| Posicionamiento físico correcto de la escena 3D con coordenadas reales | R3/R4 |
| Slices profesionales como visualización default | R4 |
| Colorbar técnica con densidad absoluta | R4 |

---

## 4. Contrato espacial objetivo

El contrato espacial es el conjunto de objetos que definen dónde está el proyecto geográficamente, con qué nivel de confianza, y qué se puede decir honestamente sobre esa posición.

### 4.1 Definición del contrato

```
ProjectFootprint
├── type            : tipo de footprint ("bbox" | "polygon" | "local_reference" | "missing")
├── crs             : sistema de referencia ("EPSG:4326" por defecto)
├── source          : origen del footprint ("latlon" | "csv_utm" | "local_meters_anchored" | "derived" | "missing")
├── confidence      : nivel de confianza ("HIGH" | "MEDIUM" | "LOW" | "MISSING")
├── sw, se, ne, nw  : esquinas del footprint (lat/lon, opcionales si type="missing")
├── center_lat/lon  : centro geográfico (si hay anclaje)
├── extent_x_m      : extensión Este-Oeste en metros
├── extent_z_m      : extensión Norte-Sur en metros
├── warnings        : lista de advertencias técnicas
└── utm_zone        : zona UTM detectada o null (campo nuevo)

GeorefConfidence   : "HIGH" | "MEDIUM" | "LOW" | "MISSING"

SpatialReference   : CRS completo (EPSG code explícito)
```

### 4.2 Reglas del contrato

1. **Todo proyecto tiene un footprint.** Puede ser `type="missing"`, pero siempre existe el objeto.
2. **El footprint tiene confidence explícita.** No existe footprint sin nivel de confianza.
3. **El footprint tiene warnings.** Si hay ambigüedad, el warning lo dice.
4. **El reporte siempre incluye georef.** La sección es obligatoria aunque sea para decir "georreferenciación no disponible".
5. **El frontend siempre muestra el badge.** No hay estado en que la confianza se oculte.

---

## 5. Schemas propuestos

### 5.1 Modificaciones a `project_schema.py`

El schema actual ya tiene `ProjectFootprint` bien definido. Se requieren dos adiciones menores:

```python
# AGREGAR a ProjectFootprint:
class ProjectFootprint(BaseModel):
    crs: str = "EPSG:4326"
    type: str = "missing"
    sw: ProjectFootprintCorner = Field(default_factory=ProjectFootprintCorner)
    se: ProjectFootprintCorner = Field(default_factory=ProjectFootprintCorner)
    ne: ProjectFootprintCorner = Field(default_factory=ProjectFootprintCorner)
    nw: ProjectFootprintCorner = Field(default_factory=ProjectFootprintCorner)
    center_lat: Optional[float] = None    # NUEVO — centro geográfico
    center_lon: Optional[float] = None    # NUEVO — centro geográfico
    extent_x_m: Optional[float] = None   # NUEVO — extensión Este-Oeste
    extent_z_m: Optional[float] = None   # NUEVO — extensión Norte-Sur
    utm_zone: Optional[str] = None       # NUEVO — ej. "19S", null si desconocido
    source: str = "missing"
    confidence: str = "MISSING"
    warnings: List[str] = Field(default_factory=list)
    precision_notes: List[str] = Field(default_factory=list)  # NUEVO
```

### 5.2 Nuevo schema `GeorefSummary` (para respuestas de API)

```python
class GeorefSummary(BaseModel):
    """Resumen compacto de georreferenciación para respuestas de API."""
    confidence: str = "MISSING"           # "HIGH" | "MEDIUM" | "LOW" | "MISSING"
    type: str = "missing"                 # tipo de footprint
    source: str = "missing"              # origen de coordenadas
    has_footprint: bool = False
    has_center: bool = False
    utm_zone: Optional[str] = None
    warnings: List[str] = Field(default_factory=list)
```

### 5.3 Modificaciones a `ProjectResponse`

`ProjectResponse` ya tiene `georef_confidence` y `footprint`. El problema es que `build_project_response()` no los popula. No se requiere cambio en el schema, solo en la función de construcción.

```python
# MODIFICAR build_project_response en project_api.py:
def build_project_response(project_id: str, meta: dict | None) -> ProjectResponse:
    footprint_data = meta.get("footprint") if meta else None
    footprint = None
    if footprint_data and isinstance(footprint_data, dict):
        try:
            footprint = ProjectFootprint(**footprint_data)
        except Exception:
            footprint = None
    
    return ProjectResponse(
        project_id=project_id,
        latitude=meta.get("latitude") if meta else None,
        longitude=meta.get("longitude") if meta else None,
        crs=meta.get("crs", "EPSG:4326") if meta else "EPSG:4326",
        created_at=meta.get("created_at") if meta else None,
        updated_at=meta.get("updated_at") if meta else None,
        run_count=count_project_runs(project_id),
        georef_confidence=meta.get("georef_confidence", "LOW") if meta else "LOW",  # AGREGAR
        footprint=footprint,  # AGREGAR
    )
```

### 5.4 Nuevo endpoint: `ProjectFootprintResponse`

```python
class ProjectFootprintResponse(BaseModel):
    project_id: str
    georef_confidence: str = "MISSING"
    georef_type: str = "local_reference"
    footprint: Optional[ProjectFootprint] = None
    coordinate_system_detected: Optional[str] = None
    utm_zone: Optional[str] = None
    warnings: List[str] = Field(default_factory=list)
    source_run_id: Optional[str] = None  # run_id de donde vino el footprint
```

### 5.5 Ejemplo JSON de footprint completo

```json
{
  "project_id": "csv_hvc_2026_05_18",
  "georef_confidence": "LOW",
  "georef_type": "local_meters_anchored",
  "footprint": {
    "crs": "EPSG:4326",
    "type": "bbox",
    "source": "local_meters_anchored",
    "confidence": "LOW",
    "center_lat": -22.28,
    "center_lon": -68.89,
    "extent_x_m": 49679.0,
    "extent_z_m": 48995.0,
    "utm_zone": null,
    "sw": {"lat": -22.5012, "lon": -69.1234},
    "se": {"lat": -22.5012, "lon": -68.6566},
    "ne": {"lat": -22.0588, "lon": -68.6566},
    "nw": {"lat": -22.0588, "lon": -69.1234},
    "warnings": [
      "Metros locales anclados al punto central. Orientación y escala real no garantizadas.",
      "El footprint es una estimación derivada, no un polígono real del survey."
    ],
    "precision_notes": [
      "Aproximación equirectangular — error <1% para extensiones <100km."
    ]
  },
  "coordinate_system_detected": "local_meters",
  "utm_zone": null,
  "warnings": [
    "Metros locales anclados al punto central. Orientación y escala real no garantizadas."
  ],
  "source_run_id": "run_csv_2026-05-18T07-24-34-652Z"
}
```

---

## 6. Clasificación de georreferenciación

### 6.1 Niveles de confianza

| Nivel | Código | Badge color | Descripción |
|-------|--------|-------------|-------------|
| Alta | `HIGH` | Verde | Las coordenadas del CSV son lat/lon WGS84 reales. El footprint puede ubicar geográficamente las observaciones. |
| Media | `MEDIUM` | Amarillo | Coordenadas UTM o lat/lon con ancla central. El footprint es aproximado. La posición es plausible pero no verificada matemáticamente. |
| Baja | `LOW` | Naranja | Metros locales con ancla lat/lon, o UTM sin zona. El footprint es una estimación derivada con incertidumbre de orientación y escala. |
| Sin georreferenciación | `MISSING` | Rojo | Sin coordenadas absolutas. Solo sistema de referencia local. No es posible ubicar geográficamente el modelo. |

### 6.2 Tipos de footprint

| Tipo | Código | Descripción |
|------|--------|-------------|
| BBox lat/lon | `latlon` | CSV tiene lat/lon reales. Footprint derivado directamente de las observaciones. |
| BBox UTM | `csv_utm` | CSV tiene coordenadas UTM. Footprint anclado a punto central. Zona UTM desconocida. |
| Metros locales anclados | `local_meters_anchored` | CSV en metros locales + punto central lat/lon. Footprint estimado por centro + extensión. |
| Referencia derivada | `derived` | Sistema de coordenadas desconocido + ancla lat/lon. Footprint muy aproximado. |
| Referencia local | `local_reference` | Sin anclaje geográfico. Footprint no puede calcularse. |
| Sin datos | `missing` | Sin información de coordenadas válida. |

### 6.3 Tabla de combinaciones: capacidades por nivel

| Confidence | Tipo | Permite terreno real | Permite ubicar voxels | Permite reporte georef | Warning obligatorio |
|------------|------|---------------------|-----------------------|----------------------|---------------------|
| HIGH | latlon | Sí (bbox real) | Futuro (R3) | Sí | Solo si extent >100km |
| MEDIUM | csv_utm | Sí (bbox estimado) | Futuro (R3) | Sí, con reservas | "UTM sin zona" siempre |
| MEDIUM | latlon sin ancla | Sí (bbox estimado) | Futuro (R3) | Sí, con reservas | "Sin punto central" |
| LOW | local_meters_anchored | Solo contexto visual | No | Sí, con disclaimer fuerte | "Orientación no garantizada" |
| LOW | derived | Solo contexto visual | No | Sí, con disclaimer fuerte | "Sistema de coordenadas desconocido" |
| MISSING | local_reference | No recomendado | No | Declarar "sin georef" | "Sin coordenadas absolutas" |
| MISSING | missing | No | No | Declarar "sin georef" | "Sin coordenadas absolutas" |

---

## 7. Comportamiento por tipo de CSV

Para cada caso de entrada, se define la respuesta esperada del sistema.

### Caso 1: CSV con lat/lon por estación

**Ejemplo:** Columnas `lon`, `lat`, `g`, `unit`.  
**Detección:** `coordinate_system = "latlon"`, `confidence = "alta"`.  
**Resultado:**
- Confidence: `HIGH` (si hay ancla lat/lon central) o `MEDIUM` (si no hay ancla).
- Footprint type: `latlon`.
- Footprint: calculado directamente desde las observaciones (bbox real del survey).
- Terreno: sí, bbox desde footprint real.
- Warning si extent > 100km: "Extent lat/lon convertido supera 100km; usar pyproj en etapa futura."
- UI: badge verde `HIGH` o amarillo `MEDIUM`.
- Reporte: sección georef completa.

### Caso 2: CSV con UTM + zona declarada en columna

**Ejemplo:** Columnas `easting`, `northing`, `zone`, `g`, `unit`.  
**Situación actual:** El sistema no lee la columna `zone` — la detección de UTM no extrae zona.  
**Resultado según R1:**
- Confidence: `MEDIUM` (no `HIGH` porque zona UTM no verificada en el backend).
- Footprint type: `csv_utm`.
- `utm_zone`: se debe leer de la columna si existe. Si no existe columna `zone`, `utm_zone = null`.
- Warning: "Zona UTM detectada del CSV. Verificar que corresponde a la región del proyecto."
- UI: badge amarillo `MEDIUM`.

### Caso 3: CSV con UTM sin zona

**Ejemplo:** Columnas `x_m`, `z_m` con valores de easting/northing sin columna de zona.  
**Resultado:**
- Confidence: `MEDIUM` con ancla, `LOW` sin ancla.
- Warning obligatorio: "UTM detectado sin zona explícita. El footprint derivado puede estar desplazado si la zona es incorrecta."
- Footprint type: `csv_utm`.
- `utm_zone`: `null`.
- No bloquear flujo — solo advertir.

### Caso 4: CSV con metros locales + lat/lon central

**Ejemplo:** Columnas `x_m`, `z_m` (valores de 0 a 50000) + usuario entrega lat/lon en el formulario.  
**Caso real HVC:** 251 pts, 0-50km en x_m y z_m, lat=-22.28, lon=-68.89.  
**Resultado:**
- Confidence: `LOW`.
- Footprint type: `local_meters_anchored`.
- Footprint: calculado con `compute_footprint_from_center(lat, lon, x_extent, z_extent)`.
- Warning: "Metros locales anclados al punto central. Orientación y escala real no garantizadas."
- Warning: "El footprint es una estimación derivada, no un polígono real del survey."
- UI: badge naranja `LOW`.
- Reporte: disclaimer fuerte en sección georef.
- Terreno: permitido pero marcado como "solo contexto visual, no co-registrado".

### Caso 5: CSV con metros locales sin lat/lon

**Ejemplo:** Columnas `x_m`, `z_m` pero usuario no entrega lat/lon.  
**Resultado:**
- Confidence: `MISSING`.
- Footprint type: `local_reference`.
- Footprint: `null` (no se puede calcular sin ancla).
- Warning: "Sin lat/lon de anclaje. Georreferenciación no disponible."
- UI: badge rojo `MISSING`.
- Reporte: sección georef declara "modelo sin ubicación geográfica".
- Terreno: no recomendado. Si usuario tiene lat/lon de contexto puede cargarlo, pero UI debe advertir.

### Caso 6: CSV con 4 esquinas entregadas por usuario

**Situación:** No implementado en R1. Esta funcionalidad es R2 (UI de polígono/bbox explícito).  
**Respuesta en R1:** No se implementa. Se documenta como capacidad futura en el tipo `polygon`.

### Caso 7: CSV con bbox entregado por usuario

**Situación:** Igual que Caso 6. No implementado en R1.

### Caso 8: CSV con polygon/GeoJSON futuro

**Situación:** Requiere `type="polygon"` y parser GeoJSON. No implementado en R1.

### Caso 9: CSV HVC-like con coordenadas locales y lat/lon incorrecta

**Caso real:** HVC CSV (Highland Valley Copper, BC, Canadá) con lat=-22.28, lon=-68.89 (Atacama, Chile).  
**Problema:** El sistema NO puede detectar esta inconsistencia. Las coordenadas locales del CSV son válidas internamente. El punto central Atacama es válido como número. No hay forma matemática de detectar que no corresponden.  
**Resultado:**
- Confidence: `LOW` (metros locales + ancla).
- Warning generado: "Metros locales anclados al punto central. Orientación y escala real no garantizadas."
- **No se genera warning adicional** sobre la inconsistencia HVC/Atacama — el sistema no puede saberlo.
- **Decisión R1:** Agregar en el formulario UI un campo de confirmación: "¿El punto lat/lon central corresponde realmente al área del survey?" con nota de que el sistema no puede verificar la correspondencia.
- **Reporte:** Sección georef incluye disclaimer: "La correspondencia entre coordenadas locales del CSV y el punto central de anclaje no fue verificada matemáticamente."

### Caso 10: CSV sin coordenadas válidas

**Ejemplo:** Columnas vacías, NaN, o sistema completamente desconocido.  
**Resultado:**
- Confidence: `MISSING`.
- Footprint type: `missing`.
- Footprint: objeto con `type="missing"`, todas las esquinas null.
- Warning: "Sin coordenadas válidas en el CSV."
- No bloquear inversión (la inversión puede ejecutarse en metros locales).
- UI: badge rojo `MISSING`.

---

## 8. Persistencia y archivos generados

### 8.1 Decisión de persistencia

| Dato | Archivo | Estado actual | R1 |
|------|---------|---------------|-----|
| `latitude`, `longitude` | `project_meta.json` | Existe | Mantener |
| `georef_confidence` | `project_meta.json` | Existe pero no siempre | Garantizar siempre |
| `georef_type` | `project_meta.json` | Existe pero no siempre | Renombrar a `footprint_source` o mantener |
| `footprint` (4 esquinas) | `project_meta.json` | Existe si x_extent>0 | Garantizar siempre (incluso si type=missing) |
| `utm_zone` | Ninguno | No existe | Agregar a `project_meta.json` y a `footprint` |
| `precision_notes` | Ninguno | No existe | Agregar a `footprint` en project_meta.json |
| `coordinate_transform` | `gravity_import_metadata.json` | Existe | Mantener |
| Georef en reporte | `report.json` | No existe | Agregar sección en R1-BE-5 |
| Footprint en parquet | `block_model.parquet` | No existe | NO en R1. R3. |

### 8.2 Estructura objetivo de `project_meta.json`

```json
{
  "project_id": "string",
  "latitude": -22.28,
  "longitude": -68.89,
  "crs": "EPSG:4326",
  "created_at": "2026-05-18T07:24:34Z",
  "updated_at": "2026-05-18T07:24:34Z",
  "source": "csv_import",
  "georef_confidence": "LOW",
  "georef_type": "local_meters_anchored",
  "utm_zone": null,
  "footprint": {
    "crs": "EPSG:4326",
    "type": "bbox",
    "source": "local_meters_anchored",
    "confidence": "LOW",
    "center_lat": -22.28,
    "center_lon": -68.89,
    "extent_x_m": 49679.0,
    "extent_z_m": 48995.0,
    "utm_zone": null,
    "sw": {"lat": -22.5012, "lon": -69.1234},
    "se": {"lat": -22.5012, "lon": -68.6566},
    "ne": {"lat": -22.0588, "lon": -68.6566},
    "nw": {"lat": -22.0588, "lon": -69.1234},
    "warnings": ["Metros locales anclados al punto central..."],
    "precision_notes": ["Aproximación equirectangular — error <1% para extensiones <100km."]
  }
}
```

### 8.3 Footprint cuando `type="missing"`

Incluso cuando no hay coordenadas válidas, el footprint debe persistirse como objeto explícito (no null):

```json
{
  "footprint": {
    "crs": null,
    "type": "missing",
    "source": "missing",
    "confidence": "MISSING",
    "center_lat": null,
    "center_lon": null,
    "extent_x_m": null,
    "extent_z_m": null,
    "utm_zone": null,
    "sw": null,
    "se": null,
    "ne": null,
    "nw": null,
    "warnings": ["Sin coordenadas absolutas. Modelo sin ubicación geográfica."],
    "precision_notes": []
  }
}
```

### 8.4 No se crea archivo `project_footprint.json` separado

Decisión: el footprint se mantiene en `project_meta.json`. No se crea un archivo separado. Razones:
- `project_meta.json` ya tiene el objeto `footprint`.
- Evitar fragmentación de archivos.
- El endpoint `/footprint` puede leer directamente `project_meta.json`.

---

## 9. API/Backend plan

### R1-BE-1 — Schemas

**Archivos en scope:**
- `terraquantum-backend/schemas/project_schema.py`

**Cambios exactos:**

1. Agregar campos a `ProjectFootprint`: `center_lat`, `center_lon`, `extent_x_m`, `extent_z_m`, `utm_zone`, `precision_notes`.
2. Agregar `ProjectFootprintResponse` como nuevo schema de respuesta para el endpoint dedicado.
3. Agregar `GeorefSummary` como schema compacto.
4. Actualizar `ProjectFootprintCorner` para aceptar explícitamente `None` en ambos campos (ya lo hace, verificar).

**Cambios a `ProjectMeta`:**
- Agregar campo `utm_zone: Optional[str] = None`.
- Agregar campo `footprint_source: Optional[str] = None` (alias para `georef_type` — o mantener `georef_type` para compatibilidad).

**Criterios de aceptación R1-BE-1:**
- [ ] `ProjectFootprint` tiene `center_lat`, `center_lon`, `extent_x_m`, `extent_z_m`, `utm_zone`, `precision_notes`.
- [ ] `ProjectFootprintResponse` es un schema válido que puede ser serializado a JSON.
- [ ] `python -m compileall schemas/project_schema.py` sin errores.

---

### R1-BE-2 — Coordinate transform y footprint emission

**Archivos en scope:**
- `terraquantum-backend/services/coordinate_transform_service.py`
- `terraquantum-backend/core/geo_utils.py`
- `terraquantum-backend/api/gravity_import_api.py`

**Cambios exactos:**

**En `coordinate_transform_service.py`:**
No se cambia la lógica de detección. Solo se documenta que `_utm_to_local_meters` no detecta zona UTM. No se agrega pyproj.

**En `core/geo_utils.py`:**
Modificar `compute_footprint_from_center()` para retornar el objeto `ProjectFootprint` completo (no solo las 4 esquinas como dict), incluyendo los nuevos campos `center_lat`, `center_lon`, `extent_x_m`, `extent_z_m`.

```python
# MODIFICAR compute_footprint_from_center:
def compute_footprint_from_center(
    center_lat: float,
    center_lon: float,
    extent_x_m: float,
    extent_z_m: float,
    source: str = "derived",
    confidence: str = "LOW",
    warnings: list[str] | None = None,
    precision_notes: list[str] | None = None,
    utm_zone: str | None = None,
) -> dict:
    """Retorna dict compatible con ProjectFootprint schema."""
    # ... cálculo de esquinas existente ...
    return {
        "crs": "EPSG:4326",
        "type": "bbox",
        "source": source,
        "confidence": confidence,
        "center_lat": float(center_lat),
        "center_lon": float(center_lon),
        "extent_x_m": float(extent_x_m),
        "extent_z_m": float(extent_z_m),
        "utm_zone": utm_zone,
        "sw": {"lat": ..., "lon": ...},
        "se": {"lat": ..., "lon": ...},
        "ne": {"lat": ..., "lon": ...},
        "nw": {"lat": ..., "lon": ...},
        "warnings": warnings or [],
        "precision_notes": precision_notes or ["Aproximación equirectangular — error <1% para extensiones <100km."],
    }
```

**En `gravity_import_api.py`:**

1. Modificar `_classify_georef()` para retornar también `utm_zone` (actualmente retorna solo confidence, type, warnings). Signature nuevo: `-> tuple[str, str, str | None, list[str]]`.

2. Garantizar que footprint se persiste incluso cuando `x_extent_m = 0` (footprint de tipo `missing`).

3. Agregar `georef_confidence`, `georef_type`, `utm_zone` al response body de `/invert`:
```python
return {
    ...
    "georef": {
        "confidence": georef_confidence,
        "type": georef_type,
        "utm_zone": utm_zone,
        "warnings": georef_warnings,
        "footprint": footprint,
    },
    ...
}
```

4. Calcular y retornar georef en `/preview` (sin persistir):
```python
# Al final del response de /preview:
ct = result.coordinate_transform
georef_confidence, georef_type, utm_zone, georef_warnings = _classify_georef(ct, None, None)
return {
    ...
    "georef_preview": {
        "confidence": georef_confidence,
        "type": georef_type,
        "utm_zone": utm_zone,
        "warnings": georef_warnings,
        "note": "Calculado sin punto central de anclaje. Confianza puede subir si se provee lat/lon."
    },
    ...
}
```

**Criterios de aceptación R1-BE-2:**
- [ ] `/invert` response tiene campo `georef` con confidence, type, utm_zone, warnings y footprint.
- [ ] `/preview` response tiene campo `georef_preview` con confidence estimada (sin ancla).
- [ ] `compute_footprint_from_center` retorna dict con `center_lat`, `center_lon`, `extent_x_m`, `extent_z_m`.
- [ ] `_classify_georef` retorna 4 valores (incluye `utm_zone`).
- [ ] Si `x_extent_m = 0`, el footprint se persiste como `type="missing"` (no como null).
- [ ] `python -m compileall api/gravity_import_api.py core/geo_utils.py` sin errores.

---

### R1-BE-3 — Endpoint `GET /projects/{project_id}/footprint`

**Archivos en scope:**
- `terraquantum-backend/api/project_api.py`
- `terraquantum-backend/core/block_model_store.py` (solo lectura)

**Cambios exactos:**

1. Corregir `build_project_response()` para poblar `georef_confidence` y `footprint`:
```python
def build_project_response(project_id: str, meta: dict | None) -> ProjectResponse:
    footprint_data = meta.get("footprint") if meta else None
    footprint = None
    if footprint_data and isinstance(footprint_data, dict):
        try:
            footprint = ProjectFootprint(**footprint_data)
        except Exception:
            footprint = None
    return ProjectResponse(
        ...,
        georef_confidence=meta.get("georef_confidence", "MISSING") if meta else "MISSING",
        footprint=footprint,
    )
```

2. Agregar endpoint `GET /projects/{project_id}/footprint`:
```python
@router.get("/{project_id}/footprint", response_model=ProjectFootprintResponse)
async def get_project_footprint(project_id: str):
    project_id = clean_project_id_or_400(project_id)
    project_dir = get_project_dir(project_id)
    if not project_dir.exists():
        raise HTTPException(status_code=404, detail="Proyecto no encontrado.")
    
    meta = load_project_meta(project_id) or {}
    footprint_data = meta.get("footprint")
    footprint = None
    if footprint_data and isinstance(footprint_data, dict):
        try:
            footprint = ProjectFootprint(**footprint_data)
        except Exception:
            footprint = None
    
    return ProjectFootprintResponse(
        project_id=project_id,
        georef_confidence=meta.get("georef_confidence", "MISSING"),
        georef_type=meta.get("georef_type", "local_reference"),
        footprint=footprint,
        coordinate_system_detected=meta.get("footprint", {}).get("source") if meta.get("footprint") else None,
        utm_zone=meta.get("utm_zone"),
        warnings=meta.get("footprint", {}).get("warnings", []) if meta.get("footprint") else [],
    )
```

**Criterios de aceptación R1-BE-3:**
- [ ] `GET /projects/{project_id}/footprint` existe y retorna HTTP 200.
- [ ] Para proyecto con footprint HIGH, retorna confidence="HIGH" y 4 esquinas válidas.
- [ ] Para proyecto sin footprint, retorna confidence="MISSING" y footprint con type="missing".
- [ ] `GET /projects/{project_id}` retorna `georef_confidence` correcto (no "LOW" por defecto).
- [ ] `python -m compileall api/project_api.py` sin errores.

---

### R1-BE-4 — `report_generator.py`: sección de georreferenciación

**Archivos en scope:**
- `terraquantum-backend/reporting/report_generator.py`
- `terraquantum-backend/core/block_model_store.py` (solo lectura, para cargar project_meta)

**Cambios exactos:**

1. Leer `project_meta.json` en `generate_technical_report_html()`:
```python
from core.block_model_store import get_project_meta_path, load_project_meta

def generate_technical_report_html(project_id: str, run_id: str) -> str:
    ...
    project_meta = load_project_meta(project_id) or {}  # NUEVO
    footprint_data = project_meta.get("footprint")       # NUEVO
    georef_confidence = project_meta.get("georef_confidence", "MISSING")  # NUEVO
    ...
    georef_section = _georef_section_html(georef_confidence, footprint_data)  # NUEVO
    ...
```

2. Implementar `_georef_section_html()` que genera una sección HTML con:
   - Nivel de confianza (HIGH/MEDIUM/LOW/MISSING) con color y texto descriptivo.
   - Tipo de footprint.
   - Esquinas del footprint si están disponibles.
   - Warnings de georreferenciación.
   - Disclaimer honesto según el nivel de confianza.

**UX copy para cada nivel en el reporte:**

```
HIGH:
"Las coordenadas del CSV son lat/lon WGS84. El footprint es una representación
geográfica directa de las observaciones. La posición del modelo es geográficamente
defensable dentro de la precisión de la aproximación equirectangular (<1% para
extensiones <100km)."

MEDIUM:
"Coordenadas UTM detectadas sin zona UTM verificada, o lat/lon sin punto central
de anclaje. El footprint es una estimación aproximada. La posición del modelo es
plausible pero no verificada matemáticamente. Requiere revisión profesional antes
de usar en interpretación geológica."

LOW:
"Metros locales anclados al punto central del usuario, o sistema de coordenadas de
baja confianza. El footprint es una estimación derivada con incertidumbre en
orientación y escala. El terreno visible en la UI es contexto visual, no topografía
co-registrada con el survey."

MISSING:
"Sin coordenadas absolutas disponibles. El modelo opera en un sistema de referencia
local sin ubicación geográfica. No es posible afirmar dónde está el modelo en el
mapa. El terreno no debe interpretarse como correspondiente al área del survey."
```

**Criterios de aceptación R1-BE-4:**
- [ ] `GET /export-report?project_id=X&run_id=Y` retorna HTML con sección "Georreferenciación".
- [ ] La sección tiene el nivel de confianza con descripción honesta.
- [ ] La sección tiene el tipo de footprint.
- [ ] La sección tiene warnings si existen.
- [ ] Para MISSING: el disclaimer es explícito y prominente.
- [ ] `python -m compileall reporting/report_generator.py` sin errores.

---

### R1-BE-5 — Tests automáticos

**Archivos en scope:**
- `terraquantum-backend/tests/test_geo_utils.py` (existe — agregar casos)
- `terraquantum-backend/tests/test_coordinate_transform.py` (existe — agregar casos)
- `terraquantum-backend/tests/test_project_geospatial.py` (existe — revisar y ampliar)
- Nuevo: `terraquantum-backend/tests/test_r1_footprint_endpoint.py`

**Tests requeridos:**

```python
# test_geo_utils.py — AGREGAR:
def test_compute_footprint_includes_center_and_extents():
    """Footprint debe incluir center_lat, center_lon, extent_x_m, extent_z_m."""

def test_compute_footprint_type_missing_when_no_extent():
    """Si extent_x_m = 0, footprint type = missing."""

# test_coordinate_transform.py — AGREGAR:
def test_classify_georef_latlon_high_with_anchor():
    """latlon + confidence alta + anchor → HIGH, type=latlon."""

def test_classify_georef_utm_no_zone_medium():
    """UTM + anchor → MEDIUM, utm_zone=null, warning obligatorio."""

def test_classify_georef_local_meters_low():
    """local_meters + anchor → LOW, type=local_meters_anchored."""

def test_classify_georef_no_anchor_missing():
    """local_meters sin anchor → MISSING, type=local_reference."""

def test_classify_georef_returns_four_values():
    """_classify_georef retorna 4 valores: confidence, type, utm_zone, warnings."""

# test_project_geospatial.py — VERIFICAR/AMPLIAR:
def test_get_project_footprint_endpoint_returns_footprint():
    """GET /projects/{project_id}/footprint retorna HTTP 200 con footprint."""

def test_get_project_response_includes_georef_confidence():
    """GET /projects/{project_id} retorna georef_confidence real (no 'LOW' por defecto)."""

# test_r1_footprint_endpoint.py — NUEVO:
def test_footprint_endpoint_404_on_missing_project():
    """GET /projects/nonexistent/footprint retorna 404."""

def test_footprint_endpoint_returns_missing_when_no_meta():
    """GET /projects/{id}/footprint retorna confidence=MISSING si sin meta."""

def test_report_html_has_georef_section():
    """HTML exportado contiene sección de georreferenciación."""
```

**Criterios de aceptación R1-BE-5:**
- [ ] `python -m pytest tests/test_geo_utils.py tests/test_coordinate_transform.py tests/test_project_geospatial.py tests/test_r1_footprint_endpoint.py -v` pasa sin errores.
- [ ] Tests no modifican `data/projects/` (usan tmp_path o fixtures).

---

## 10. Frontend plan

### R1-FE-1 — Tipos API en `frontendApi.ts`

**Archivos en scope:**
- `terraquantum-web/lib/terraquantum/frontendApi.ts`

**Cambios exactos:**

```typescript
// AGREGAR tipos nuevos:

export type GeorefConfidence = "HIGH" | "MEDIUM" | "LOW" | "MISSING";

export type FootprintCorner = {
  lat: number | null;
  lon: number | null;
};

export type ProjectFootprint = {
  crs: string | null;
  type: "bbox" | "polygon" | "local_reference" | "missing";
  source: "latlon" | "csv_utm" | "local_meters_anchored" | "derived" | "missing";
  confidence: GeorefConfidence;
  center_lat: number | null;
  center_lon: number | null;
  extent_x_m: number | null;
  extent_z_m: number | null;
  utm_zone: string | null;
  sw: FootprintCorner | null;
  se: FootprintCorner | null;
  ne: FootprintCorner | null;
  nw: FootprintCorner | null;
  warnings: string[];
  precision_notes: string[];
};

export type GeorefSummary = {
  confidence: GeorefConfidence;
  type: string;
  source: string;
  utm_zone: string | null;
  warnings: string[];
  footprint: ProjectFootprint | null;
};

export type ProjectFootprintResponse = {
  project_id: string;
  georef_confidence: GeorefConfidence;
  georef_type: string;
  footprint: ProjectFootprint | null;
  coordinate_system_detected: string | null;
  utm_zone: string | null;
  warnings: string[];
};
```

**Agregar función de fetch:**
```typescript
export async function fetchProjectFootprint(
  projectId: string
): Promise<FrontendApiResult<ProjectFootprintResponse>> {
  // GET /projects/{projectId}/footprint
}
```

**Criterios de aceptación R1-FE-1:**
- [ ] `cmd /c npx eslint lib/terraquantum/frontendApi.ts` sin errores.
- [ ] Los tipos exportan correctamente y son importables.

---

### R1-FE-2 — `GravityCsvPreviewPanel.tsx`: badge de confianza

**Archivos en scope:**
- `terraquantum-web/componentes/GravityCsvPreviewPanel.tsx`

**Cambios exactos:**

El panel de preview ya muestra `coordinate_transform`. Agregar:
1. Leer `georef_preview.confidence` del response de `/preview` (una vez implementado R1-BE-2).
2. Mostrar un badge de color antes de la inversión: "Confianza de georreferenciación: [badge]".
3. Mostrar warnings de georef en texto claro.

**Badge component (inline, no componente separado):**
```typescript
// Badge de confianza
const GEOREF_BADGE_STYLE: Record<string, string> = {
  HIGH:    "bg-green-100 text-green-800 border border-green-300",
  MEDIUM:  "bg-yellow-100 text-yellow-800 border border-yellow-300",
  LOW:     "bg-orange-100 text-orange-800 border border-orange-300",
  MISSING: "bg-red-100 text-red-800 border border-red-300",
};

const GEOREF_BADGE_LABEL: Record<string, string> = {
  HIGH:    "Georreferenciación ALTA",
  MEDIUM:  "Georreferenciación MEDIA",
  LOW:     "Georreferenciación BAJA — Solo contexto visual",
  MISSING: "Sin georreferenciación",
};
```

**Criterios de aceptación R1-FE-2:**
- [ ] El panel de preview muestra el badge de confianza.
- [ ] El badge tiene el color correcto según el nivel.
- [ ] `cmd /c npx eslint componentes/GravityCsvPreviewPanel.tsx` sin errores.

---

### R1-FE-3 — `GeoDashboard.tsx`: footprint y confianza

**Archivos en scope:**
- `terraquantum-web/componentes/huds/GeoDashboard.tsx`

**Cambios exactos:**

El `GeoDashboard` actualmente muestra voxel trace. Agregar sección de georreferenciación:
1. Fetch de `GET /projects/{projectId}/footprint` cuando hay `activeRun` con `projectId`.
2. Mostrar: nivel de confianza (badge), tipo de footprint, advertencias.
3. Si confidence = MISSING: mensaje destacado "Modelo sin ubicación geográfica".
4. Si confidence = LOW: nota "Terreno = solo contexto visual".

**Criterios de aceptación R1-FE-3:**
- [ ] `GeoDashboard` muestra sección de georreferenciación cuando hay corrida activa.
- [ ] Badge de confianza es visible.
- [ ] Warnings aparecen en texto.
- [ ] `cmd /c npx eslint componentes/huds/GeoDashboard.tsx` sin errores.

---

### R1-FE-4 — `DatosView.tsx` / `ProjectRunList.tsx`: georef en historial

**Archivos en scope:**
- `terraquantum-web/componentes/DatosView.tsx`
- `terraquantum-web/componentes/datos/ProjectRunList.tsx`

**Cambios exactos:**

En la lista de proyectos/corridas históricas:
1. `ProjectRunList` consume `georef_confidence` del response de `GET /projects` (una vez que `build_project_response` lo popule).
2. Mostrar badge de confianza por proyecto en la lista.
3. Tooltip con `footprint.type` y warnings principales.

**Criterios de aceptación R1-FE-4:**
- [ ] La lista de historial muestra badge de georreferenciación por proyecto.
- [ ] `cmd /c npx eslint componentes/DatosView.tsx componentes/datos/ProjectRunList.tsx` sin errores.

---

### R1-FE-5 — `useAppStore.ts`: estado de georef

**Archivos en scope:**
- `terraquantum-web/store/useAppStore.ts`

**Cambios exactos:**

Agregar campos al store para mantener el footprint de la corrida activa:

```typescript
// AGREGAR a AppState:
projectFootprint: ProjectFootprint | null;
georefConfidence: GeorefConfidence | null;
georefWarnings: string[];

// AGREGAR acciones:
setProjectFootprint: (footprint: ProjectFootprint | null) => void;
setGeorefConfidence: (confidence: GeorefConfidence | null) => void;
setGeorefWarnings: (warnings: string[]) => void;
```

**Cuándo poblar el store:**
- Cuando se completa la inversión (`/invert` response incluye `georef`).
- Cuando se carga desde historial (fetch de `/projects/{projectId}/footprint`).
- Cuando se resetea `activeRun`, limpiar footprint.

**Criterios de aceptación R1-FE-5:**
- [ ] `useAppStore` tiene campos `projectFootprint`, `georefConfidence`, `georefWarnings`.
- [ ] El store se actualiza correctamente al completar inversión.
- [ ] El store se limpia al resetear la corrida activa.
- [ ] `cmd /c npx eslint store/useAppStore.ts` sin errores.

---

### R1-FE-6 — UX copy honesto

El texto del frontend debe ser honesto y técnico. No usar "georreferenciación industrial" ni "posición exacta".

**UX copy aprobado por nivel:**

```
HIGH:
"Georreferenciación ALTA — El CSV tiene coordenadas lat/lon directas.
El footprint representa las observaciones reales del survey."

MEDIUM:
"Georreferenciación MEDIA — Coordenadas aproximadas.
El footprint es una estimación, no una posición verificada matemáticamente."

LOW:
"Georreferenciación BAJA — Metros locales anclados a punto central.
El terreno en la visualización es contexto visual, no topografía co-registrada."

MISSING:
"Sin georreferenciación — El modelo no tiene ubicación geográfica.
No es posible afirmar dónde está la anomalía en el mapa."
```

**UX copy para el caso de correspondencia no verificada (local_meters + lat/lon):**
```
"Nota: el sistema no puede verificar que el punto lat/lon central 
corresponda al área real del survey CSV. Confirme antes de interpretar 
el terreno como correspondiente a los datos."
```

**Criterios de aceptación R1-FE-6:**
- [ ] Ningún texto dice "georreferenciación exacta" o "posición precisa" sin calificador.
- [ ] Ningún texto dice "industrial" para la georreferenciación.
- [ ] Los badges tienen tooltips con explicación técnica.

---

## 11. Reporte técnico y UX copy

### 11.1 Sección de georreferenciación en reporte HTML

La sección `_georef_section_html()` en `report_generator.py` debe generar:

```html
<section id="georef">
  <h2>Georreferenciación del Proyecto</h2>
  
  <div class="georef-badge georef-{LOW|MEDIUM|HIGH|MISSING}">
    Nivel de confianza: {nivel}
  </div>
  
  <table>
    <tr><th>Sistema de coordenadas detectado</th><td>{detected}</td></tr>
    <tr><th>Tipo de footprint</th><td>{type}</td></tr>
    <tr><th>Origen del footprint</th><td>{source}</td></tr>
    <tr><th>Zona UTM</th><td>{utm_zone o "Desconocida"}</td></tr>
    <tr><th>Centro geográfico</th><td>{center_lat}, {center_lon} o "N/A"</td></tr>
    <tr><th>Extensión del survey</th><td>{extent_x_m} m E-O × {extent_z_m} m N-S o "N/A"</td></tr>
    <tr><th>Esquina SW</th><td>{sw.lat}, {sw.lon} o "N/A"</td></tr>
    <tr><th>Esquina NE</th><td>{ne.lat}, {ne.lon} o "N/A"</td></tr>
  </table>
  
  <div class="georef-warnings">
    <strong>Advertencias de georreferenciación:</strong>
    <ul>
      {warnings}
    </ul>
  </div>
  
  <div class="georef-disclaimer">
    {texto de disclaimer según nivel — ver Sección 9.4}
  </div>
</section>
```

### 11.2 Texto prohibido en reporte

- NO: "La anomalía está ubicada en..." (sin decir el nivel de confianza).
- NO: "Coordenadas verificadas".
- NO: "Posición exacta del depósito".
- SÍ: "El footprint es una estimación con confianza [nivel]".
- SÍ: "Requiere validación profesional de la correspondencia geográfica".

---

## 12. Tests automáticos requeridos

### 12.1 Tests unitarios

```python
# Módulo: tests/test_geo_utils.py (ampliar)
test_compute_footprint_from_center_returns_four_corners()
test_compute_footprint_includes_center_and_extents()
test_compute_footprint_type_missing_when_extent_zero()
test_compute_footprint_equirectangular_accuracy_under_100km()
test_compute_footprint_warns_when_over_100km()

# Módulo: tests/test_coordinate_transform.py (ampliar)
test_classify_georef_latlon_high_confidence_with_anchor()
test_classify_georef_latlon_high_confidence_without_anchor()
test_classify_georef_utm_with_anchor_medium()
test_classify_georef_utm_without_anchor_low()
test_classify_georef_local_meters_with_anchor_low()
test_classify_georef_local_meters_without_anchor_missing()
test_classify_georef_unknown_with_anchor_low()
test_classify_georef_unknown_without_anchor_missing()
test_classify_georef_returns_four_values_including_utm_zone()

# Módulo: tests/test_project_geospatial.py (ampliar)
test_build_project_response_includes_georef_confidence_from_meta()
test_build_project_response_includes_footprint_from_meta()
test_build_project_response_georef_missing_when_no_meta()

# Módulo: tests/test_r1_footprint_endpoint.py (nuevo)
test_footprint_endpoint_200_for_project_with_meta()
test_footprint_endpoint_404_for_nonexistent_project()
test_footprint_endpoint_returns_missing_for_project_without_footprint()
test_footprint_confidence_high_for_latlon_csv()
test_footprint_confidence_low_for_local_meters_csv()
test_invert_response_includes_georef_field()
test_preview_response_includes_georef_preview_field()
test_report_html_contains_georef_section()
```

### 12.2 Tests de integración

```python
# test_r1_integration.py (nuevo)
def test_full_flow_latlon_csv_produces_high_confidence():
    """CSV con lat/lon → /invert → project_meta.json tiene confidence=HIGH."""

def test_full_flow_local_meters_with_anchor_produces_low():
    """CSV local_meters + anchor → /invert → confidence=LOW, type=local_meters_anchored."""

def test_footprint_persisted_in_project_meta():
    """Después de /invert, GET /projects/{id}/footprint retorna el footprint guardado."""

def test_project_meta_footprint_never_null_after_invert():
    """Incluso para CSV sin coordenadas válidas, project_meta.json tiene footprint (con type=missing)."""
```

---

## 13. QA manual requerido

### 13.1 Dataset lat/lon pequeño

**Dataset:** CSV con columnas `station_id`, `lat`, `lon`, `g`, `unit`, `gravity_type`, `x_m`, `z_m` donde `x_m=lon*factor`, `z_m=lat*factor`.  
**Expectativa:**
- `georef_confidence = HIGH`.
- Badge verde en UI.
- Footprint tipo `latlon` con 4 esquinas en el rango lat/lon del CSV.
- Reporte HTML sección georef con nivel HIGH y sin warnings críticos.

### 13.2 Dataset UTM con zona (simulado)

**Dataset:** CSV con `x_m`, `z_m` en valores de UTM easting/northing (>100,000) + columna `zone="19S"`.  
**Expectativa:**
- `georef_confidence = MEDIUM`.
- Badge amarillo en UI.
- `utm_zone = "19S"` en el footprint.
- Warning: "UTM detectado" en el reporte.

### 13.3 Dataset local_meters con central lat/lon

**Dataset:** HVC CSV (251 pts, 0-50km en x_m/z_m) + lat=-22.28, lon=-68.89 entregado por usuario.  
**Expectativa:**
- `georef_confidence = LOW`.
- Badge naranja en UI.
- Footprint tipo `local_meters_anchored` con extensión ~50km×49km.
- Reporte HTML con disclaimer fuerte: "orientación y escala no garantizadas".
- Nota: "Correspondencia con punto central no verificada matemáticamente".

### 13.4 Dataset local_meters sin lat/lon

**Dataset:** CSV con `x_m`, `z_m` pero usuario no entrega lat/lon (o lat/lon son inválidos).  
**Expectativa:**
- `georef_confidence = MISSING`.
- Badge rojo en UI.
- Footprint tipo `local_reference`.
- Reporte HTML con sección georef declarando "sin ubicación geográfica".
- El sistema no bloquea la inversión — solo informa.

### 13.5 HVC completo (validación de comportamiento)

**Dataset:** `CORE-REAL-9_source_gravity_HVC_fixed.csv` + lat=-22.28, lon=-68.89.  
**Expectativa:**
- `georef_confidence = LOW` (local_meters + ancla).
- Footprint calculado: SW≈(-22.5, -69.1), NE≈(-22.0, -68.6).
- Warning en reporte: "Coordenadas CSV son locales (metros). El punto central es Atacama, no Highland Valley Copper."
- Nota visible en UI: "El sistema no puede verificar la correspondencia entre CSV y punto central."

---

## 14. Riesgos y decisiones pendientes

### 14.1 Decisión: pyproj (Opción A vs Opción B)

**Situación actual:** `pyproj` no está en `requirements.txt`. Se usa aproximación equirectangular en `coordinate_transform_service.py` con warning si extent > 100 km.

**Opción A (recomendada para R1):**
- No instalar pyproj en R1.
- Mantener aproximación equirectangular con warning explícito.
- Bloquear `confidence=HIGH` cuando extent > 100 km (downgrade a MEDIUM automático).
- Documentar como tarea pendiente para R2.
- **Pro:** No agrega dependencia nueva. No rompe el Docker. R1 puede completarse sin coordinar instalación.
- **Contra:** Para surveys grandes (>100km), el error de posición puede superar el 1%.

**Opción B:**
- Agregar `pyproj>=3.6` a `requirements.txt` en R1.2 o en R2.
- Usar pyproj para lat/lon → UTM → local exacto.
- **Pro:** Corrección geodésica real para cualquier extensión.
- **Contra:** Dependencia nueva. Requiere validación Docker. Puede romper el entorno Windows del desarrollador.

**Decisión recomendada en esta spec: Opción A.** pyproj se agrega en R2 con planning separado. R1 es la fase de exposición del contrato espacial, no de mejora de precisión geodésica.

**Regla de bloqueo para HIGH (R1):**
```python
# En _classify_georef:
if cs == "latlon" and conf != "low":
    extent_x = getattr(ct, "x_extent_m", 0) or 0
    extent_z = getattr(ct, "z_extent_m", 0) or 0
    if max(extent_x, extent_z) > 100_000:
        warns.append("Extent > 100km: precisión equirectangular limitada. Usar pyproj en R2.")
        # confidence = MEDIUM (no HIGH) para surveys grandes
        if has_anchor:
            return "MEDIUM", "latlon", None, warns
    if has_anchor:
        return "HIGH", "latlon", None, []
```

### 14.2 Riesgo: `project_meta.json` legacy sin footprint

**Problema:** Proyectos creados con versiones anteriores del sistema tienen `project_meta.json` sin campo `footprint` o con `footprint=null`.  
**Mitigación:** El endpoint `GET /projects/{project_id}/footprint` debe manejar `footprint=null` retornando `confidence=MISSING` con nota "Proyecto sin footprint calculado. Re-ejecutar inversión para actualizar."

### 14.3 Riesgo: usuario entrega lat/lon incorrecto

**Problema:** El sistema no puede verificar que el punto central corresponda al área del CSV.  
**Mitigación:** Warning siempre presente en `LOCAL` y `MEDIUM`: "La correspondencia entre coordenadas del CSV y el punto central no fue verificada matemáticamente."  
No hay forma técnica de detectar la inconsistencia sin una fuente de verdad externa (ej. mapa de regiones conocidas). No implementar en R1.

### 14.4 Riesgo: UTM zone faltante

**Problema:** Un CSV con UTM zona 19S y uno con UTM zona 33N se procesan idénticamente. El footprint resultante puede estar en el lugar equivocado si el usuario no sabe la zona.  
**Mitigación R1:** Warning obligatorio en toda corrida con UTM: "Zona UTM no detectada automáticamente. Verificar que el punto central corresponda a la zona correcta."  
**Mitigación R2:** Campo `utm_zone` en el formulario de importación (usuario declara la zona).

### 14.5 Riesgo: frontend mostrando terreno como real cuando confidence=LOW

**Problema:** El terreno DEM se carga siempre que hay lat/lon, independientemente del nivel de confianza.  
**Mitigación R1:** Agregar leyenda permanente en el viewport 3D cuando `georefConfidence` es LOW o MISSING: "Terreno: solo contexto visual — no co-registrado con el survey."  
**No** deshabilitar el terreno — es útil como contexto aunque no sea exacto.

### 14.6 Riesgo: datasets > 100 km con aproximación equirectangular

**Problema:** HVC tiene extensión de ~50km×50km. Está dentro del límite. Pero un survey de 200km×200km tendría error > 1%.  
**Mitigación R1:** Warning automático cuando extent > 100 km. Confidence downgrade a MEDIUM máximo aunque el sistema sea lat/lon.

### 14.7 Riesgo: `project_meta.json` creado desde `POST /projects` sin footprint

**Problema:** Si el usuario crea el proyecto vía API antes de subir el CSV, el `project_meta.json` se crea con `georef_confidence="LOW"` y `footprint=null`. El footprint solo se actualiza si `project_meta_path` no existe al momento de `/invert`.  
**Mitigación R1:** Modificar `/invert` para SIEMPRE actualizar `georef_confidence` y `footprint` en `project_meta.json`, no solo si no existe.

### 14.8 Riesgo: aliases legacy en JSON y consumidores externos

Los campos `recommendation`, `risk_level`, `probability` siguen en `report.json`. No son parte de R1. Son parte de R0 pendiente. No tocar en esta fase.

---

## 15. Plan de ejecución recomendado

### Orden de subfases

```
Día 1 (backend schemas + lógica):
  R1-BE-1: Schemas (30-45 min)
  R1-BE-2: Coordinate transform + footprint emission (90-120 min)

Día 2 (backend APIs):
  R1-BE-3: Endpoint /footprint + fix build_project_response (60-90 min)
  R1-BE-4: Report generator (60-90 min)
  R1-BE-5: Tests automáticos (90-120 min)

Día 3 (frontend):
  R1-FE-1: Tipos API (30 min)
  R1-FE-5: Store (45 min)
  R1-FE-2: GravityCsvPreviewPanel badge (60 min)
  R1-FE-3: GeoDashboard georef section (60-90 min)
  R1-FE-4: DatosView/ProjectRunList badge (45 min)
  R1-FE-6: UX copy review (30 min)

Día 4 (QA manual):
  QA-1: Dataset lat/lon → HIGH
  QA-2: Dataset local_meters + anchor → LOW
  QA-3: HVC → LOW, warning correspondencia
  QA-4: Sin coordenadas → MISSING
  QA-5: Reporte HTML → sección georef presente
  QA-6: Frontend build → lint sin errores

Total estimado: 3-4 días de trabajo enfocado.
```

### Prerequisitos antes de comenzar R1

- [ ] A2.1 (BUG DatosView/setActiveRun) cerrado o en curso paralelo.
- [ ] Backend corriendo localmente sin errores.
- [ ] Frontend compilando sin errores.
- [ ] `python -m pytest tests/` pasa (al menos los 4 tests core existentes).

### Criterio de cierre de R1

- [ ] `GET /projects/{project_id}/footprint` existe y retorna datos correctos.
- [ ] `GET /projects/{project_id}` retorna `georef_confidence` real.
- [ ] `/invert` response incluye campo `georef` con confidence y footprint.
- [ ] `/preview` response incluye campo `georef_preview`.
- [ ] `project_meta.json` tiene `footprint` (nunca null, incluso si type=missing).
- [ ] Reporte HTML tiene sección "Georreferenciación".
- [ ] Frontend muestra badge de confianza en preview, en GeoDashboard, y en historial.
- [ ] `cmd /c npm run lint` pasa sin errores.
- [ ] `python -m pytest tests/` pasa con los tests nuevos de R1.
- [ ] QA manual de 4 datasets completado y documentado.

---

## 16. Prompts de ejecución sugeridos

### Prompt R1-BE-1 — Schemas

```
Rol: Arquitecto backend Python/FastAPI.

Tarea: Modificar schemas en `terraquantum-backend/schemas/project_schema.py`.

Archivos permitidos:
- terraquantum-backend/schemas/project_schema.py

Archivos prohibidos: Ningún otro archivo. NO tocar gravity_import_schema.py. NO tocar APIs.

Cambios exactos a realizar:
1. En `ProjectFootprint`, agregar campos opcionales:
   - center_lat: Optional[float] = None
   - center_lon: Optional[float] = None
   - extent_x_m: Optional[float] = None
   - extent_z_m: Optional[float] = None
   - utm_zone: Optional[str] = None
   - precision_notes: List[str] = Field(default_factory=list)

2. En `ProjectMeta`, agregar campo:
   - utm_zone: Optional[str] = None

3. Crear nuevo schema `GeorefSummary`:
   - confidence: str = "MISSING"
   - type: str = "missing"
   - source: str = "missing"
   - has_footprint: bool = False
   - has_center: bool = False
   - utm_zone: Optional[str] = None
   - warnings: List[str] = Field(default_factory=list)

4. Crear nuevo schema `ProjectFootprintResponse`:
   - project_id: str
   - georef_confidence: str = "MISSING"
   - georef_type: str = "local_reference"
   - footprint: Optional[ProjectFootprint] = None
   - coordinate_system_detected: Optional[str] = None
   - utm_zone: Optional[str] = None
   - warnings: List[str] = Field(default_factory=list)
   - source_run_id: Optional[str] = None

Validación: `python -m compileall schemas/project_schema.py` sin errores.

Respuesta final obligatoria:
1. Archivo modificado: schemas/project_schema.py
2. Cambios aplicados: lista exacta.
3. `python -m compileall schemas/project_schema.py` → resultado.
4. Qué NO se tocó.
5. Riesgos pendientes.
```

---

### Prompt R1-BE-2 — Coordinate transform y footprint emission

```
Rol: Arquitecto backend Python/FastAPI.

Contexto:
- TerraQuantum tiene `_classify_georef()` en gravity_import_api.py que clasifica georef en HIGH/MEDIUM/LOW/MISSING.
- `compute_footprint_from_center()` en core/geo_utils.py calcula 4 esquinas pero no incluye center_lat/lon ni extent_x/z.
- Los schemas en project_schema.py ya fueron actualizados (R1-BE-1 completado).

Tarea: Modificar lógica de footprint y clasificación de georef.

Archivos permitidos:
- terraquantum-backend/api/gravity_import_api.py
- terraquantum-backend/core/geo_utils.py

Archivos prohibidos: NO tocar coordinate_transform_service.py. NO tocar project_schema.py. NO tocar otros servicios.

Cambios exactos:

1. En `core/geo_utils.py`, modificar `compute_footprint_from_center()`:
   - Agregar parámetros: source, confidence, warnings, precision_notes, utm_zone.
   - Retornar dict con TODOS los campos del schema ProjectFootprint actualizado (incluyendo center_lat, center_lon, extent_x_m, extent_z_m, utm_zone, precision_notes).
   - Mantener la lógica de cálculo de esquinas existente sin cambios.

2. En `api/gravity_import_api.py`:
   a. Modificar `_classify_georef()` para retornar 4 valores: (confidence, type, utm_zone, warnings).
      - utm_zone es siempre None por ahora (no se detecta automáticamente).
      - Agregar downgrade a MEDIUM cuando extent > 100km y sistema es latlon.
   b. Modificar el bloque de persistencia en `/invert`:
      - SIEMPRE actualizar `georef_confidence` y `footprint` en project_meta.json (no solo si no existe).
      - Cuando x_extent_m = 0: persistir footprint con type="missing".
   c. Agregar `georef` al response body de `/invert` con: confidence, type, utm_zone, warnings, footprint dict.
   d. Al final del response de `/preview`: calcular `georef_preview` con `_classify_georef(ct, None, None)` y retornarlo.

Validación:
- `python -m compileall api/gravity_import_api.py core/geo_utils.py`
- Un CSV lat/lon local small → /invert → response tiene georef.confidence = "HIGH".
- CSV con extent > 100km → response tiene warning de equirectangular.

Respuesta final obligatoria:
1. Archivos modificados.
2. Cambios aplicados: lista exacta por archivo.
3. Resultados de `python -m compileall`.
4. Casos de prueba manuales ejecutados.
5. Qué NO se tocó.
6. Riesgos pendientes.
```

---

### Prompt R1-BE-3 — Endpoint footprint y fix build_project_response

```
Rol: Arquitecto backend Python/FastAPI.

Contexto:
- R1-BE-1 y R1-BE-2 están completados.
- `project_api.py` tiene `build_project_response()` que NO popula `georef_confidence` ni `footprint`.
- `ProjectResponse` schema ya tiene esos campos.
- No existe endpoint `GET /projects/{project_id}/footprint`.

Tarea: Corregir project_api.py.

Archivos permitidos:
- terraquantum-backend/api/project_api.py

Archivos prohibidos: NO tocar ningún otro archivo.

Cambios exactos:

1. Importar `ProjectFootprint, ProjectFootprintResponse` desde `schemas.project_schema`.

2. Modificar `build_project_response()`:
   - Leer `georef_confidence` del meta dict (default "MISSING").
   - Leer `footprint` del meta dict, construir `ProjectFootprint(**footprint_data)` con manejo de excepción.
   - Retornar `ProjectResponse` con estos campos poblados.

3. Agregar endpoint:
   @router.get("/{project_id}/footprint", response_model=ProjectFootprintResponse)
   async def get_project_footprint(project_id: str):
       # Lee project_meta.json
       # Construye ProjectFootprintResponse
       # Si el proyecto no existe: 404
       # Si no hay footprint en meta: retornar confidence="MISSING", footprint con type="missing"

Validación:
- `python -m compileall api/project_api.py`
- `GET /projects/{id}` retorna georef_confidence correcta.
- `GET /projects/{id}/footprint` retorna HTTP 200 con footprint.
- `GET /projects/noexiste/footprint` retorna HTTP 404.

Respuesta final obligatoria:
1. Archivo modificado.
2. Cambios exactos aplicados.
3. Resultados de compilación.
4. Pruebas manuales realizadas.
5. Qué NO se tocó.
6. Riesgos.
```

---

### Prompt R1-BE-4 — Report generator

```
Rol: Arquitecto backend Python/FastAPI.

Contexto:
- R1-BE-1, R1-BE-2, R1-BE-3 completados.
- `reporting/report_generator.py` genera HTML sin sección de georreferenciación.
- `core/block_model_store.py` tiene `load_project_meta()`.

Tarea: Agregar sección de georreferenciación al reporte HTML.

Archivos permitidos:
- terraquantum-backend/reporting/report_generator.py

Archivos prohibidos: NO tocar ningún otro archivo.

Cambios exactos:

1. En `generate_technical_report_html()`:
   - Importar `load_project_meta` desde `core.block_model_store`.
   - Cargar `project_meta = load_project_meta(project_id) or {}`.
   - Extraer `georef_confidence`, `georef_type`, footprint data.
   - Llamar a nueva función `_georef_section_html(georef_confidence, footprint_data)`.
   - Incluir el resultado en el HTML antes de la sección de favorabilidad.

2. Implementar `_georef_section_html(confidence: str, footprint_data: dict | None) -> str`:
   - Badge de color por nivel (HIGH=verde, MEDIUM=amarillo, LOW=naranja, MISSING=rojo).
   - Tabla con: sistema detectado, tipo, fuente, zona UTM, centro geográfico, extensión, esquinas SW y NE.
   - Lista de warnings de georef.
   - Disclaimer por nivel (ver Sección 9.4 del spec R1).

UX copy para disclaimers (ver Sección 11.1 de este documento).

Validación:
- `python -m compileall reporting/report_generator.py`
- `GET /export-report?project_id=X&run_id=Y` → HTML contiene `<section id="georef">`.
- Para proyecto con confidence=LOW: disclaimer fuerte visible.
- Para proyecto con confidence=MISSING: mensaje "sin ubicación geográfica" presente.

Respuesta final obligatoria:
1. Archivo modificado.
2. Cambios exactos.
3. Compilación.
4. Prueba manual del reporte.
5. Qué NO se tocó.
6. Riesgos.
```

---

### Prompt R1-FE-1 — Tipos y fetch frontend

```
Rol: Arquitecto frontend React/TypeScript/Next.js.

Contexto:
- R1 backend completado (endpoints, schemas, reportes).
- `terraquantum-web/lib/terraquantum/frontendApi.ts` tiene la API pública del frontend.
- No existe ningún tipo para footprint ni georef en el frontend.

Tarea: Agregar tipos y función de fetch para footprint.

Archivos permitidos:
- terraquantum-web/lib/terraquantum/frontendApi.ts
- terraquantum-web/store/useAppStore.ts

Archivos prohibidos: NO tocar componentes ni otros archivos.

Cambios en frontendApi.ts:
1. Agregar tipo `GeorefConfidence = "HIGH" | "MEDIUM" | "LOW" | "MISSING"`.
2. Agregar tipo `FootprintCorner = { lat: number | null; lon: number | null }`.
3. Agregar tipo `ProjectFootprint` (ver Sección 5 del spec R1).
4. Agregar tipo `GeorefSummary` (ver Sección 5.2 del spec R1).
5. Agregar tipo `ProjectFootprintResponse` (ver Sección 5.4 del spec R1).
6. Agregar función `fetchProjectFootprint(projectId: string): Promise<FrontendApiResult<ProjectFootprintResponse>>`.

Cambios en useAppStore.ts:
1. Agregar campos: `projectFootprint: ProjectFootprint | null`, `georefConfidence: GeorefConfidence | null`, `georefWarnings: string[]`.
2. Agregar acciones: `setProjectFootprint`, `setGeorefConfidence`, `setGeorefWarnings`.
3. En el reset de activeRun, limpiar footprint (setProjectFootprint(null)).

Validación:
- `cmd /c npx eslint lib/terraquantum/frontendApi.ts store/useAppStore.ts`
- Sin errores TypeScript.
- Los tipos son importables.

Respuesta final obligatoria:
1. Archivos modificados.
2. Tipos agregados: lista.
3. Funciones agregadas.
4. Resultado de ESLint.
5. Qué NO se tocó.
6. Riesgos.
```

---

### Prompt R1-QA — QA manual

```
Rol: QA engineer de TerraQuantum.

Contexto:
- R1 backend y frontend completados.
- El sistema está corriendo localmente (backend en puerto 8010, frontend en 3000).

Tarea: Ejecutar QA manual de R1 con 4 datasets.

NO modificar código. Solo leer logs, respuestas de API, y UI.

Para cada dataset:
1. Hacer la llamada o usar la UI.
2. Verificar el resultado esperado.
3. Documentar el resultado real.
4. Reportar PASS o FAIL con evidencia.

Datasets y resultados esperados:

QA-1: CSV lat/lon pequeño
- Resultado esperado: confidence=HIGH, badge verde, footprint con 4 esquinas.
- Verificar en: response de /preview, response de /invert, GET /footprint, reporte HTML.

QA-2: HVC CSV con lat=-22.28, lon=-68.89 (local_meters)
- Resultado esperado: confidence=LOW, badge naranja, footprint tipo local_meters_anchored.
- Verificar: warning sobre correspondencia no verificada en reporte y UI.

QA-3: CSV con x_m/z_m sin lat/lon
- Resultado esperado: confidence=MISSING, badge rojo, footprint tipo local_reference.
- Verificar: reporte HTML dice "sin ubicación geográfica".

QA-4: CSV UTM (simulado con valores >100000 en x_m/z_m)
- Resultado esperado: confidence=MEDIUM, badge amarillo, warning "UTM sin zona".
- Verificar: utm_zone=null en response.

Respuesta final obligatoria:
1. QA-1: PASS/FAIL + evidencia.
2. QA-2: PASS/FAIL + evidencia.
3. QA-3: PASS/FAIL + evidencia.
4. QA-4: PASS/FAIL + evidencia.
5. Riesgos identificados durante QA.
6. FAILs documentados con paso de reproducción exacto.
7. Confirmación de que no se modificó ningún código.
```

---

*Fin de la especificación R1.*

*Próxima actualización: al completar cada subfase R1-BE o R1-FE, actualizar el criterio de cierre correspondiente.*  
*Este documento NO reemplaza el TERRAQUANTUM_INDUSTRIAL_REALITY_BIBLE.md — lo complementa para la fase R1.*
