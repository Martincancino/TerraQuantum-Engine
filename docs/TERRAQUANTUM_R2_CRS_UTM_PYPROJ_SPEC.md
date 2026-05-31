# TERRAQUANTUM — R2 CRS, UTM ZONE, PYPROJ DECISION Y VALIDACIÓN GEODÉSICA

**Versión:** 1.0  
**Fecha:** 2026-05-19  
**Autor:** Claude Code — Auditoría completa de código fuente + diseño arquitectónico  
**Estado:** ESPECIFICACIÓN EJECUTABLE — ACTIVA  
**Fuentes:** Código fuente auditado en solo lectura: `requirements.txt`, `schemas/project_schema.py`, `schemas/gravity_import_schema.py`, `services/coordinate_transform_service.py`, `core/geo_utils.py`, `api/gravity_import_api.py`, `api/project_api.py`, `tests/test_*.py` (14 archivos), `lib/terraquantum/frontendApi.ts`, `store/useAppStore.ts`, `docs/TERRAQUANTUM_R1_SPATIAL_CONTRACT_SPEC.md`, `docs/TERRAQUANTUM_HVC_VALIDATION_V1.md`, `docs/TERRAQUANTUM_INDUSTRIAL_REALITY_BIBLE.md`

---

> **Propósito de este documento:**  
> Especificación técnica completa para la fase R2 — CRS real, zona UTM, decisión sobre pyproj y validación geodésica. Define exactamente qué existe hoy (post-R1), qué problemas persisten, cómo resolverlos en orden de riesgo, y qué queda para R3. Cada sección termina en criterios concretos o decisiones explícitas.

---

## 1. Dictamen R2

### 1.1 Veredicto técnico

R1 está completado y verificado en código fuente. Los esquemas están implementados, los endpoints existen, la clasificación de georef retorna 4 valores, el footprint se persiste en `project_meta.json`, y el frontend tiene tipos y store para georef. **R1-QA es PASS.**

Sin embargo, R1 dejó 10 problemas intencionales que R2 debe resolver:

1. `utm_zone` siempre es `None` — hardcodeado en `_classify_georef()` línea 92-159 de `gravity_import_api.py`.
2. UTM sin zona se trata como `MEDIUM` con warning, pero no hay campo obligatorio para que el usuario lo declare.
3. El CRS guardado en `project_meta.json` es siempre `"EPSG:4326"` aunque el input sea UTM (semánticamente incorrecto).
4. `pyproj` no está instalado — confirmado en `requirements.txt` (17 líneas, pyproj ausente).
5. La conversión lat/lon→metros usa aproximación equirectangular en 3 lugares: `_latlon_to_local_meters()` (L46-97 de `coordinate_transform_service.py`), `compute_footprint_from_center()` (L99-175 de `geo_utils.py`) y `compute_bbox()` (L10-39 de `geo_utils.py`).
6. Surveys >100 km: el sistema emite warning pero no hay límite duro. Para extensiones entre 100-300 km el error puede ser 1-5%.
7. El sistema no puede transformar UTM easting/northing → lat/lon sin zona UTM verificada.
8. No existe campo UI obligatorio para zona UTM (el formulario de importación no tiene ese campo).
9. No existe validación de EPSG real ni tabla de lookup UTM→EPSG.
10. No existe política clara para bloquear datasets con CRS insuficiente.

### 1.2 Decisión principal de R2

R2 construye el **contrato CRS** sobre la cadena de exposición espacial que R1 estableció.

R2 hace:
- Introduce el concepto `CrsContract` con campos: `input_crs`, `epsg_code`, `crs_source`, `crs_confidence`, `utm_zone`, `utm_hemisphere`.
- Agrega campo UI para zona UTM en el formulario de importación.
- Agrega parser para leer columna `zone`/`utm_zone`/`zona_utm` del CSV.
- Implementa lookup `utm_zone + hemisphere → EPSG code`.
- Clasifica `crs_source`: `user_declared | csv_column | inferred | missing`.
- Define política de degradación/bloqueo según CRS disponible.

R2 NO hace (queda para R3):
- Elevación absoluta de voxels (`voxel_absolute_elevation`).
- DEM co-registrado con footprint real.
- Modificaciones a `Scene3D`.
- Modificaciones al solver.
- Modificaciones a MS-x.

---

## 2. Estado actual post-R1

### 2.1 Respuestas a las preguntas obligatorias de auditoría

**P1. ¿pyproj está instalado hoy?**

**NO.** `requirements.txt` tiene 17 dependencias: fastapi, uvicorn, pydantic, numpy, polars, scipy, trimesh, networkx, python-multipart, PyMaxflow, shapely, earthengine-api, pytest, pytest-cov, structlog, slowapi. pyproj está ausente.

**P2. ¿Qué funciones usan aproximación equirectangular?**

Exactamente 3 funciones en 2 archivos:

| Función | Archivo | Líneas | Uso |
|---------|---------|--------|-----|
| `_latlon_to_local_meters()` | `services/coordinate_transform_service.py` | 46-97 | Convierte lat/lon a metros locales para el solver |
| `compute_footprint_from_center()` | `core/geo_utils.py` | 99-175 | Calcula 4 esquinas de footprint desde centro + extents |
| `compute_bbox()` | `core/geo_utils.py` | 10-39 | Calcula bbox con buffer para pedido de terreno |

Las 3 usan la fórmula `meters_per_deg_lon = METERS_PER_DEG_LAT * cos(lat)` donde `METERS_PER_DEG_LAT = 111_320.0`.

**P3. ¿Dónde se detecta UTM hoy?**

En dos lugares:
1. `gravity_import_service.py` (no auditado directamente, pero inferido de `CoordSystemDetection`): detecta UTM por rangos de valores (easting > 100,000 m típicamente).
2. `coordinate_transform_service.py:transform_coordinates()` (L196-210): dispatch a `_utm_to_local_meters()` si `detected == "utm" and confidence != "low"`.

La función `_utm_to_local_meters()` (L100-130) hace **solo normalización de origen SW** — shift para que el mínimo sea 0. No detecta zona. No reproyecta. Retorna `precision_notes: ["No se realizo reproyeccion geografica. Solo normalizacion de origen local."]`.

En `_classify_georef()` (L88-159 de `gravity_import_api.py`): el caso `cs == "utm"` genera `MEDIUM` + warning sobre zona no verificada, pero **siempre retorna `utm_zone=None`** (hardcoded en el comentario de la función: "utm_zone is always None in R1").

**P4. ¿Qué columnas UTM reconoce el parser?**

El parser actual detecta el sistema de coordenadas por **rangos de valores numéricos**, no por nombre de columna. No lee explícitamente una columna llamada `zone` o `utm_zone`. Las columnas de coordenadas reconocidas son `x_m` y `z_m` (canonizadas internamente). No existe lógica para extraer zona UTM de ninguna columna del CSV.

**P5. ¿Se puede detectar zona UTM desde columnas existentes?**

**Parcialmente y con incertidumbre:**
- Si el CSV tiene una columna `zone`, `utm_zone`, `zona_utm` o similar → el parser actual NO la lee. Se puede agregar en R2 (R2-BE-2).
- Inferencia por rango de valores: easting 100,000–900,000 m confirma UTM, pero no identifica zona (múltiples zonas tienen el mismo rango de easting).
- Inferencia aproximada posible: si el usuario provee lat/lon central, se puede calcular la zona UTM teórica. Error posible si la zona real difiere (surveys en límite de zona).

**P6. ¿Qué campos de schema faltan para R2?**

Campos ausentes del contrato CRS que R2 debe agregar:

| Campo | Tipo | Descripción |
|-------|------|-------------|
| `input_crs` | `Optional[str]` | CRS real del CSV input ("EPSG:4326", "EPSG:32619", "local_meters", "unknown") |
| `epsg_code` | `Optional[int]` | Código EPSG numérico (32619 para UTM 19S, 4326 para WGS84) |
| `crs_source` | `str` | Origen del CRS: "user_declared" \| "csv_column" \| "inferred" \| "missing" |
| `crs_confidence` | `str` | Confianza del CRS: "HIGH" \| "MEDIUM" \| "LOW" \| "MISSING" |
| `utm_hemisphere` | `Optional[str]` | "N" \| "S" \| null |
| `horizontal_datum` | `Optional[str]` | "WGS84" \| "NAD83" \| "SIRGAS2000" \| null |
| `vertical_datum` | `Optional[str]` | "EGM96" \| "MSL" \| null — solo si elevación está en el CSV |

**P7. ¿Qué debería guardar `project_meta.json` para R2?**

Además de los campos R1 (ya implementados):
```json
{
  "input_crs": "EPSG:32719",
  "epsg_code": 32719,
  "crs_source": "user_declared",
  "utm_hemisphere": "S",
  "horizontal_datum": "WGS84",
  "vertical_datum": null,
  "footprint": {
    "... todos los campos R1 ...",
    "utm_hemisphere": "S",
    "epsg_code": 32719,
    "crs_source": "user_declared",
    "crs_confidence": "HIGH"
  }
}
```

**P8. ¿Qué debería guardar `gravity_import_metadata.json` para R2?**

En el campo `coordinate_transform`, agregar:
```json
{
  "... campos actuales ...",
  "utm_zone": "19S",
  "utm_hemisphere": "S",
  "epsg_code": 32719,
  "crs_source": "user_declared"
}
```

**P9. ¿Qué debería mostrar el frontend para R2?**

En el formulario de importación CSV:
- Campo `utm_zone` (opcional, texto: ej. "19S"): aparece cuando el sistema detecta UTM en el preview.
- Campo `utm_hemisphere` (dropdown N/S): aparece junto con utm_zone.
- EPSG derivado (readonly, calculado automáticamente desde zona+hemisferio).

En el panel de preview:
- Badge `crs_source` junto al badge de georef_confidence.
- Si UTM detectado: "Zona UTM detectada del CSV (sin zona explícita). Declarar zona para mejorar precisión."

En GeoDashboard y reporte:
- EPSG code del proyecto.
- crs_source explicado.

**P10. ¿Qué tests son necesarios para no romper R1?**

Los siguientes tests de R1 deben seguir pasando sin modificación:
- `tests/test_r1_georef_contract.py` — contrato espacial R1
- `tests/test_r1_footprint_endpoint.py` — endpoint /footprint
- `tests/test_r1_report_georef.py` — sección georef en HTML
- `tests/test_geo_utils.py` — cálculos de footprint
- `tests/test_coordinate_transform.py` — transformaciones de coordenadas

Los tests de R2 son **aditivos**: no modifican tests R1, solo agregan nuevos.

### 2.2 Bug detectado en auditoría: PATCH destruye footprint

**El endpoint `PATCH /projects/{project_id}` en `project_api.py` (L183-204) reconstruye `ProjectMeta` desde cero** usando solo los campos de `ProjectUpdate`. Esto sobrescribe `footprint`, `georef_confidence`, `georef_type` y `utm_zone` con sus valores por defecto. Un PATCH de lat/lon destruye el footprint calculado por `/invert`. Este bug no es de R2, pero debe documentarse como riesgo y corregirse antes de ejecutar R2.

---

## 3. Problema CRS/UTM actual

### 3.1 Diagnóstico de la cadena CRS

```
CSV con UTM 19S   →   parser detecta "utm"   →   _utm_to_local_meters()
                                                    ↓
                                           Solo shift SW. No zona.
                                                    ↓
                              _classify_georef() retorna utm_zone=None
                                                    ↓
                              project_meta.json guarda crs="EPSG:4326"
                              utm_zone=null, epsg_code=nunca guardado
                                                    ↓
                              footprint calculado desde centro + extents
                              usando equirectangular SIN zona UTM
                                                    ↓
                              La posición puede ser incorrecta si el usuario
                              no sabe que hay error de zona
```

### 3.2 Consecuencias concretas

**Impacto 1 — CRS guardado incorrecto:**
Un CSV con coordenadas `EPSG:32719` (UTM 19S) tiene `crs = "EPSG:4326"` en el JSON. Esto es semánticamente incorrecto y rompe cualquier pipeline GIS posterior.

**Impacto 2 — Sin zona, no hay reproyección correcta:**
`_utm_to_local_meters()` hace shift al origen SW. El footprint calculado desde el centro + extents en metros es correcto en magnitud, pero la orientación podría estar mal si easting/northing de la zona no corresponde al lat/lon central.

**Impacto 3 — EPSG code ausente:**
No existe campo `epsg_code` en ningún schema. Un consumidor externo no puede determinar el CRS real del dataset.

**Impacto 4 — Equirectangular para surveys >100km:**
La advertencia existe, pero no hay límite duro. Un survey de 250km tendría error geodésico de ~3% en la posición de las esquinas del footprint.

### 3.3 Tabla de exactitud de la aproximación equirectangular

| Extent del survey | Error posición | Consecuencia |
|-------------------|----------------|--------------|
| < 50 km | < 0.25% | Aceptable para R1/R2 |
| 50-100 km | 0.25-1% | Marginal — warning existente es correcto |
| 100-200 km | 1-3% | Significativo — debería degradar a MEDIUM máximo |
| > 200 km | > 3% | Significativo — debería requerir pyproj |
| > 500 km | > 10% | Inaceptable sin pyproj |

---

## 4. Política pyproj

### 4.1 Análisis comparativo de opciones

#### Opción A — No instalar pyproj en R2

**Descripción:** Mantener aproximación equirectangular. Documentar limitaciones. No agregar dependencia.

| Aspecto | Evaluación |
|---------|------------|
| **Pros** | Sin riesgo de instalación. R2 puede centrarse en schemas/UI/zona UTM. Sin cambio en `requirements.txt`. Sin riesgo Docker. |
| **Contras** | UTM→WGS84 sigue siendo aproximado. No se puede verificar EPSG. No se puede calcular footprint preciso para surveys >100km. |
| **Riesgo Windows** | Ninguno. |
| **Riesgo Docker** | Ninguno. |
| **Tests** | Los tests actuales siguen pasando. No hay tests geodésicos nuevos posibles. |
| **Impacto requirements** | Ninguno. |
| **Impacto precisión** | Sin mejora. Error equirectangular persiste. |

#### Opción B — Instalar pyproj en R2

**Descripción:** Agregar `pyproj>=3.6.0` a `requirements.txt`. Usar Transformer para conversiones reales UTM↔WGS84.

| Aspecto | Evaluación |
|---------|------------|
| **Pros** | Transformaciones geodésicas reales. EPSG lookup nativo. Verificación de hemisferio. Footprint preciso para cualquier extent. |
| **Contras** | Dependencia nueva con componente C nativo (PROJ library). Aumenta imagen Docker. Requiere validar en Windows 11 (entorno del desarrollador). |
| **Riesgo Windows** | MEDIO. pyproj>=3.6 distribuye wheels pre-compilados para Windows x64. Sin conda, requiere pip wheel de PyPI. Puede fallar si PROJ_DATA no es encontrado automáticamente (pyproj>=3.x maneja esto internamente con el wheel). Necesita test antes de commit. |
| **Riesgo Docker** | BAJO. En imagen oficial python:3.11-slim, `pip install pyproj` funciona si se agregan dependencias de sistema (`libproj-dev` en Debian, pero el wheel de pyproj incluye PROJ). Aumenta imagen ~30MB. |
| **Tests** | Se pueden escribir tests geodésicos reales con tolerancias de metros. Más confiables que la approximación. |
| **Impacto requirements** | `requirements.txt` + 1 línea: `pyproj>=3.6.0`. |
| **Impacto precisión** | Alta mejora. Error geodésico < 1cm para cualquier extent. |

#### Opción C — Preparar schemas y UI, instalar pyproj en R2.2 (RECOMENDADA)

**Descripción:** R2.0 implementa schemas CRS, campo UTM zone en UI, parser de columna zone, lookup EPSG, y una capa de abstracción (`coordinate_transform_real.py`) con interfaces definidas pero implementación stub (equirectangular). R2.2 es un sprint independiente que instala pyproj y rellena la implementación stub con transforms reales.

| Aspecto | Evaluación |
|---------|------------|
| **Pros** | Cero riesgo de instalación en R2.0. Schemas/UI/EPSG lookup tienen valor inmediato sin pyproj. La interfaz abstracta aísla el riesgo de la implementación. R2.2 es testeable de forma independiente. |
| **Contras** | Requiere disciplina de interfaz para no acoplar código a la implementación stub. R2.2 requiere otro sprint. |
| **Riesgo Windows R2.0** | Ninguno (sin pyproj). |
| **Riesgo Windows R2.2** | MEDIO — mismo que Opción B, pero aislado en un sprint dedicado. |
| **Riesgo Docker R2.0** | Ninguno. |
| **Riesgo Docker R2.2** | BAJO — mismo que Opción B, pero aislado. |
| **Tests R2.0** | Tests de schemas, UI, lookup EPSG, clasificación CRS. Sin tests geodésicos reales. |
| **Tests R2.2** | Tests de transformaciones reales con tolerancia de metros. |
| **Impacto requirements** | R2.0: sin cambio. R2.2: + `pyproj>=3.6.0`. |
| **Impacto precisión** | R2.0: igual a R1 (equirectangular). R2.2: alta mejora. |

### 4.2 Decisión recomendada: Opción C

**Rationale:**

R2 entrega valor concreto sin riesgo de instalación:
1. El campo `utm_zone` en UI resuelve el problema más urgente: el usuario puede declarar la zona.
2. El lookup EPSG corrige el CRS guardado (de "EPSG:4326" hardcoded a "EPSG:32719" correcto).
3. La capa de abstracción garantiza que R2.2 es un cambio de una función, no una reescritura.
4. pyproj en R2.2 es testeable en 1 día de trabajo aislado, con criterios claros de accept/reject.

La decisión de No instalar pyproj en R2.0 es **reversible** — si el desarrollador instala pyproj localmente y funciona, se puede promover a R2.0 sin drama. Si no funciona, R2.0 sigue siendo válido.

### 4.3 Abstracción propuesta para R2.0

```python
# services/coordinate_transform_real.py (NUEVO)

def transform_utm_to_wgs84(
    easting: float,
    northing: float,
    utm_zone: str,      # ej. "19S"
    utm_hemisphere: str,  # "N" | "S"
    epsg_code: int,
) -> tuple[float, float]:
    """
    R2.0: stub equirectangular (no requiere pyproj).
    R2.2: reemplazar con pyproj.Transformer.
    
    Returns (latitude, longitude) en WGS84.
    """
    # R2.0 stub — retorna None (no puede transformar sin pyproj)
    raise NotImplementedError(
        "transform_utm_to_wgs84 requiere pyproj (R2.2). "
        "Use compute_footprint_from_center con lat/lon central como ancla."
    )


def get_epsg_from_utm(zone_number: int, hemisphere: str) -> int:
    """
    Lookup EPSG code desde zona UTM + hemisferio. No requiere pyproj.
    
    UTM Norte: EPSG 32601-32660 (zona 1-60 N)
    UTM Sur:   EPSG 32701-32760 (zona 1-60 S)
    """
    n = int(zone_number)
    if not (1 <= n <= 60):
        raise ValueError(f"Número de zona UTM inválido: {n}. Debe ser 1-60.")
    if hemisphere.upper() == "N":
        return 32600 + n
    if hemisphere.upper() == "S":
        return 32700 + n
    raise ValueError(f"Hemisferio inválido: {hemisphere}. Debe ser 'N' o 'S'.")
```

Esta función es pura Python, no requiere pyproj, y es testeable.

---

## 5. Contrato CRS objetivo

### 5.1 Nuevo schema `CrsContract`

```python
# AGREGAR a schemas/project_schema.py

class CrsContract(BaseModel):
    """
    Contrato CRS de R2. Describe el sistema de referencia del dataset de entrada.
    """
    input_crs: Optional[str] = None
    # CRS real del CSV input. Ej: "EPSG:32719", "EPSG:4326", "local_meters", "unknown"
    
    output_crs: str = "EPSG:4326"
    # CRS de salida geográfica. Siempre WGS84 para footprint.
    
    horizontal_datum: Optional[str] = None
    # "WGS84" | "NAD83" | "SIRGAS2000" | null
    
    vertical_datum: Optional[str] = None
    # "EGM96" | "MSL" | null — solo si el CSV tiene elevación
    
    utm_zone: Optional[str] = None
    # "19S" | "33N" | null. Formato: número 1-60 + letra N/S.
    
    utm_hemisphere: Optional[str] = None
    # "N" | "S" | null
    
    epsg_code: Optional[int] = None
    # Código EPSG numérico: 32719, 4326, etc.
    
    crs_source: str = "missing"
    # "user_declared" | "csv_column" | "inferred" | "missing"
    
    crs_confidence: str = "MISSING"
    # "HIGH" | "MEDIUM" | "LOW" | "MISSING"
```

### 5.2 Modificaciones a `ProjectFootprint` (agregar campos CRS)

```python
# AGREGAR a ProjectFootprint en schemas/project_schema.py:
class ProjectFootprint(BaseModel):
    # ... todos los campos R1 existentes ...
    
    utm_hemisphere: Optional[str] = None   # NUEVO R2 — "N" | "S"
    epsg_code: Optional[int] = None        # NUEVO R2 — código EPSG numérico
    crs_source: str = "missing"            # NUEVO R2 — origen del CRS
    crs_confidence: str = "MISSING"        # NUEVO R2 — confianza del CRS (≠ georef_confidence)
```

### 5.3 Modificaciones a `ProjectMeta` (campos CRS nivel de proyecto)

```python
# AGREGAR a ProjectMeta en schemas/project_schema.py:
class ProjectMeta(BaseModel):
    # ... todos los campos R1 existentes ...
    
    input_crs: Optional[str] = None        # NUEVO R2
    epsg_code: Optional[int] = None        # NUEVO R2
    crs_source: str = "missing"            # NUEVO R2
    utm_hemisphere: Optional[str] = None   # NUEVO R2
    horizontal_datum: Optional[str] = None # NUEVO R2
    crs_contract: Optional[CrsContract] = None  # NUEVO R2 — objeto completo
```

### 5.4 Modificaciones a `CoordSystemDetection` (schema de importación)

```python
# MODIFICAR en schemas/gravity_import_schema.py:
class CoordSystemDetection(BaseModel):
    detected: str = "unknown"
    confidence: str = "low"
    warning: Optional[str] = None
    utm_zone: Optional[str] = None         # NUEVO R2 — si detectado desde columna CSV
    utm_hemisphere: Optional[str] = None   # NUEVO R2
    epsg_code: Optional[int] = None        # NUEVO R2 — si inferido o declarado
    crs_source: str = "missing"            # NUEVO R2
```

### 5.5 Tabla de crs_confidence vs georef_confidence

Estos son dos campos distintos con semánticas distintas:

| Campo | Qué mide | Valores |
|-------|---------|---------|
| `georef_confidence` (R1) | Confianza en la posición geográfica del dataset | HIGH / MEDIUM / LOW / MISSING |
| `crs_confidence` (R2) | Confianza en que el CRS del input es conocido y correcto | HIGH / MEDIUM / LOW / MISSING |

Ejemplos:
- CSV lat/lon + zona UTM declarada → `georef_confidence=HIGH`, `crs_confidence=HIGH`
- CSV UTM + zona declarada por usuario → `georef_confidence=MEDIUM`, `crs_confidence=HIGH`
- CSV UTM + zona inferida aproximada → `georef_confidence=MEDIUM`, `crs_confidence=LOW`
- CSV metros locales + ancla → `georef_confidence=LOW`, `crs_confidence=MISSING`
- CSV UTM sin zona → `georef_confidence=MEDIUM`, `crs_confidence=LOW`

### 5.6 Tabla EPSG lookup para UTM (función pura, sin pyproj)

| Zona | Hemisferio | EPSG | Nombre |
|------|-----------|------|--------|
| 1 | N | 32601 | WGS 84 / UTM zone 1N |
| 18 | N | 32618 | WGS 84 / UTM zone 18N |
| 19 | N | 32619 | WGS 84 / UTM zone 19N |
| 19 | S | 32719 | WGS 84 / UTM zone 19S |
| 20 | S | 32720 | WGS 84 / UTM zone 20S |
| 33 | N | 32633 | WGS 84 / UTM zone 33N |
| 60 | S | 32760 | WGS 84 / UTM zone 60S |

**Fórmula:** Norte → `32600 + zona_number`, Sur → `32700 + zona_number`. Válida para todas las zonas 1-60.

---

## 6. Comportamiento por tipo de CSV

### Caso A: CSV lat/lon por estación

**Entrada:** Columnas `lat`, `lon`, `g`. Sistema detectado: `latlon`, confidence: `alta`.

**R2 comportamiento:**
- `input_crs = "EPSG:4326"`, `epsg_code = 4326`, `crs_source = "inferred"`, `crs_confidence = "HIGH"`.
- `utm_zone = null`, `utm_hemisphere = null`.
- `georef_confidence` → sigue las reglas R1 (HIGH si hay ancla, MEDIUM si no hay ancla o extent >100km).
- **Nuevo:** Si extent >200km → `crs_confidence = "MEDIUM"` y warning sobre precisión equirectangular severa.

### Caso B: CSV UTM con zona explícita en columna

**Entrada:** Columnas `easting`, `northing`, `zone` (con valor "19S"), `g`.

**R2 comportamiento (parser nuevo):**
- Parser lee columna `zone` y extrae "19S" → `utm_zone = "19S"`, `utm_hemisphere = "S"`.
- Lookup: `epsg_code = 32719`, `input_crs = "EPSG:32719"`.
- `crs_source = "csv_column"`, `crs_confidence = "HIGH"`.
- `georef_confidence = "MEDIUM"` (UTM sin reproyección real a WGS84 aún — R2.0 stub).
- **R2.2:** Con pyproj, UTM + zona declarada → `georef_confidence = "HIGH"` (si hay ancla lat/lon).

### Caso C: CSV UTM sin zona, usuario declara zona en formulario

**Entrada:** Columnas `x_m`, `z_m` (valores de easting/northing). Usuario escribe "19S" en campo UI.

**R2 comportamiento:**
- `utm_zone = "19S"`, `utm_hemisphere = "S"`, `epsg_code = 32719`.
- `crs_source = "user_declared"`, `crs_confidence = "HIGH"` (usuario declaró zona).
- `input_crs = "EPSG:32719"` → corregido desde "EPSG:4326" hardcoded.
- `georef_confidence = "MEDIUM"` (sin reproyección real aún).
- Warning si easting/northing están fuera del rango válido para la zona declarada: "Valores de easting/northing fuera del rango esperado para zona 19S. Verificar zona."

### Caso D: CSV UTM sin zona, usuario no declara zona

**Entrada:** Columnas `x_m`, `z_m` (valores UTM). Usuario no llena campo zona.

**R2 comportamiento:**
- `utm_zone = null`, `utm_hemisphere = null`, `epsg_code = null`.
- `crs_source = "missing"`, `crs_confidence = "MISSING"`.
- `input_crs = "unknown"` (ya no "EPSG:4326" incorrecto).
- `georef_confidence = "MEDIUM"` si hay ancla lat/lon, "LOW" si no hay ancla.
- Warning obligatorio: "UTM detectado sin zona. Declarar zona UTM para mejorar precisión del footprint. Campo disponible en formulario."

### Caso E: CSV UTM con EPSG explícito en columna

**Entrada:** Columna `crs` o `epsg` con valor "32719" o "EPSG:32719".

**R2 comportamiento:**
- Parser detecta y extrae EPSG: `epsg_code = 32719`.
- `input_crs = "EPSG:32719"`.
- Inferir zona + hemisferio: zona = 32719 - 32700 = 19, hemisferio = S → `utm_zone = "19S"`, `utm_hemisphere = "S"`.
- `crs_source = "csv_column"`, `crs_confidence = "HIGH"`.

### Caso F: Easting/northing fuera de rango válido para zona declarada

**Ejemplo:** Usuario declara zona "19S" pero easting > 900,000 o < 100,000.

**R2 comportamiento:**
- Emitir warning: "Easting {valor} fuera del rango válido UTM (100,000–900,000 m). Posible zona incorrecta."
- `crs_confidence = "LOW"` (zona declarada pero datos no válidos para ella).
- NO bloquear la inversión — solo advertir.

### Caso G: CSV lat/lon cruzando zona UTM

**Ejemplo:** Survey de 300km que cruza las zonas UTM 18N y 19N.

**R2 comportamiento:**
- Sistema lat/lon detectado → no aplica zona UTM al input.
- `input_crs = "EPSG:4326"`, `crs_source = "inferred"`.
- Warning automático si extent >100km: "Extent lat/lon convertido supera 100km; precisión equirectangular limitada."
- `crs_confidence = "MEDIUM"` para surveys 100-200km.
- Nota: "Survey cruza múltiples zonas UTM. pyproj requerido para corrección completa (R2.2)."

### Caso H: CSV metros locales con ancla lat/lon

**Comportamiento de R1 + adiciones R2:**
- `input_crs = "local_meters"`, `epsg_code = null`.
- `crs_source = "missing"`, `crs_confidence = "MISSING"`.
- `georef_confidence = "LOW"` (sin cambio de R1).
- Warning permanente: "Metros locales sin CRS definido. No es posible asignar EPSG al dataset."

### Caso I: CSV metros locales sin ancla

**Comportamiento de R1 + adiciones R2:**
- `input_crs = "local_meters"`, `epsg_code = null`.
- `crs_source = "missing"`, `crs_confidence = "MISSING"`.
- `georef_confidence = "MISSING"` (sin cambio de R1).
- **R2 agrega:** warning específico sobre CRS: "Sin CRS definido. Modelo sin sistema de referencia geográfico."

### Política de bloqueo/degradación R2

| Caso | georef_confidence | crs_confidence | Acción |
|------|-------------------|----------------|--------|
| lat/lon + ancla + extent <100km | HIGH | HIGH | Permitir todo. Sin warnings críticos. |
| UTM + zona declarada + ancla | MEDIUM | HIGH | Permitir inversión. Warning: "reproyección pendiente (R2.2)". |
| UTM + zona declarada + sin ancla | LOW | HIGH | Permitir inversión. Warning: "sin lat/lon central". |
| UTM sin zona + ancla | MEDIUM | MISSING | Permitir inversión. Warning urgente: "Declarar zona UTM". |
| UTM sin zona + sin ancla | LOW | MISSING | Permitir inversión. Warning doble urgente. |
| local_meters + ancla | LOW | MISSING | Permitir inversión. Disclaimer prominente. |
| local_meters sin ancla | MISSING | MISSING | Permitir inversión. Disclaimer máximo. |
| lat/lon + extent >200km | MEDIUM | MEDIUM | Permitir. Warning sobre error geodésico severo. |

**R2 NO bloquea la inversión en ningún caso.** Solo advierte. El bloqueo es para R4+ cuando se requieran datos con CRS verificado para análisis económico.

---

## 7. Backend plan

### R2-BE-1 — Schemas CRS

**Archivos en scope:**
- `terraquantum-backend/schemas/project_schema.py`
- `terraquantum-backend/schemas/gravity_import_schema.py`

**Cambios exactos:**

En `project_schema.py`:
1. Crear `CrsContract` (ver Sección 5.1).
2. Agregar campos a `ProjectFootprint`: `utm_hemisphere`, `epsg_code`, `crs_source`, `crs_confidence` (ver Sección 5.2).
3. Agregar campos a `ProjectMeta`: `input_crs`, `epsg_code`, `crs_source`, `utm_hemisphere`, `horizontal_datum`, `crs_contract` (ver Sección 5.3).

En `gravity_import_schema.py`:
1. Agregar a `CoordSystemDetection`: `utm_zone`, `utm_hemisphere`, `epsg_code`, `crs_source` (ver Sección 5.4).
2. Agregar a `CoordinateTransform`: `utm_zone`, `utm_hemisphere`, `epsg_code`, `crs_source`.

**Criterios de aceptación R2-BE-1:**
- [ ] `CrsContract` es un schema Pydantic válido y serializable a JSON.
- [ ] `ProjectFootprint` tiene `utm_hemisphere`, `epsg_code`, `crs_source`, `crs_confidence`.
- [ ] `CoordSystemDetection` tiene `utm_zone`, `utm_hemisphere`, `epsg_code`, `crs_source`.
- [ ] `python -m compileall schemas/project_schema.py schemas/gravity_import_schema.py` sin errores.
- [ ] Tests R1 pasan sin modificación.

---

### R2-BE-2 — Parser/metadata para UTM zone/EPSG

**Archivos en scope:**
- `terraquantum-backend/services/coordinate_transform_service.py` (agregar paso de utm_zone)
- `terraquantum-backend/api/gravity_import_api.py` (modificar `_classify_georef` + endpoint `/invert` para aceptar `utm_zone` como Form parameter)

**Cambios exactos:**

En `gravity_import_api.py`:
1. Agregar `utm_zone_form: Optional[str] = Form(None)` al endpoint `/invert`.
2. Modificar `_classify_georef()` para aceptar `utm_zone_form` como parámetro adicional.
3. Cuando `utm_zone_form` está provisto: intentar extraer número y hemisferio, calcular `epsg_code` usando `get_epsg_from_utm()`.
4. Cuando columna `zone` existe en el CSV (provisto por `CoordSystemDetection.utm_zone`): usar ese valor.
5. Guardar `input_crs`, `epsg_code`, `crs_source`, `utm_hemisphere` en `project_meta.json`.

Nuevo archivo `terraquantum-backend/services/coordinate_transform_real.py`:
1. Función `get_epsg_from_utm(zone_number: int, hemisphere: str) -> int` (ver Sección 4.3).
2. Función stub `transform_utm_to_wgs84(...)` que lanza `NotImplementedError` (R2.0) o usa pyproj (R2.2).
3. Función `parse_utm_zone_string(zone_str: str) -> tuple[int, str]` — parsea "19S" → (19, "S").
4. Función `validate_utm_easting_northing(easting, northing, zone_num, hemisphere) -> list[str]` — retorna warnings.

**Criterios de aceptación R2-BE-2:**
- [ ] `POST /gravity-import/invert` acepta parámetro `utm_zone_form` (opcional).
- [ ] Si usuario pasa `utm_zone_form="19S"`: `project_meta.json` tiene `utm_zone="19S"`, `utm_hemisphere="S"`, `epsg_code=32719`, `input_crs="EPSG:32719"`, `crs_source="user_declared"`.
- [ ] `get_epsg_from_utm(19, "S")` retorna `32719`.
- [ ] `get_epsg_from_utm(1, "N")` retorna `32601`.
- [ ] `parse_utm_zone_string("19S")` retorna `(19, "S")`.
- [ ] `parse_utm_zone_string("3N")` retorna `(3, "N")`.
- [ ] `parse_utm_zone_string("zona_invalida")` lanza ValueError con mensaje claro.
- [ ] `python -m compileall services/coordinate_transform_real.py api/gravity_import_api.py` sin errores.

---

### R2-BE-3 — pyproj integration o stub según decisión

**Archivos en scope:** Solo si se elige Opción B o se promueve R2.2.
- `terraquantum-backend/services/coordinate_transform_real.py` (reemplazar stub)
- `terraquantum-backend/requirements.txt` (agregar `pyproj>=3.6.0`)

**Para Opción C (R2.0 stub — recomendado):** No modificar archivos. El stub de R2-BE-2 es suficiente.

**Para Opción B o R2.2:**

```python
# requirements.txt — AGREGAR:
pyproj>=3.6.0

# coordinate_transform_real.py — IMPLEMENTAR:
from pyproj import Transformer

def transform_utm_to_wgs84(
    easting: float,
    northing: float,
    epsg_code: int,
) -> tuple[float, float]:
    transformer = Transformer.from_crs(
        f"EPSG:{epsg_code}",
        "EPSG:4326",
        always_xy=True,
    )
    lon, lat = transformer.transform(easting, northing)
    return lat, lon

def transform_latlon_to_utm(
    lat: float,
    lon: float,
    epsg_code: int,
) -> tuple[float, float]:
    transformer = Transformer.from_crs(
        "EPSG:4326",
        f"EPSG:{epsg_code}",
        always_xy=True,
    )
    easting, northing = transformer.transform(lon, lat)
    return easting, northing
```

**Criterios de aceptación R2-BE-3 (si se implementa):**
- [ ] `python -c "from pyproj import Transformer; print('OK')"` sin errores en Windows y Docker.
- [ ] `transform_utm_to_wgs84(easting=580000, northing=5650000, epsg_code=32619)` retorna lat≈51.0, lon≈-78.0 (zona 19N, ejemplo Quebec).
- [ ] `python -m compileall services/coordinate_transform_real.py` sin errores.
- [ ] Tests R1 pasan sin modificación.

---

### R2-BE-4 — coordinate_transform_service real CRS

**Archivos en scope:**
- `terraquantum-backend/services/coordinate_transform_service.py`

**Cambios exactos:**

1. En `_utm_to_local_meters()`: si `detection.utm_zone` está provisto (de R2-BE-2), emitir nota de precisión diferente: "UTM zona {zona} detectada. Normalización de origen local aplicada. Reproyección geodésica pendiente (R2.2)."

2. Pasar `crs_source` del `detection` al `CoordinateTransform` retornado (nuevo campo en schema).

3. En `_latlon_to_local_meters()`: agregar `crs_source = "inferred"` al CoordinateTransform (lat/lon siempre se asume WGS84, es una inferencia razonable).

**Criterios de aceptación R2-BE-4:**
- [ ] CSV UTM con zona declarada → `coordinate_transform.utm_zone = "19S"`, `coordinate_transform.crs_source = "user_declared"`.
- [ ] CSV lat/lon → `coordinate_transform.crs_source = "inferred"`.
- [ ] Tests de `test_coordinate_transform.py` pasan.
- [ ] `python -m compileall services/coordinate_transform_service.py` sin errores.

---

### R2-BE-5 — gravity_import_api warnings/response

**Archivos en scope:**
- `terraquantum-backend/api/gravity_import_api.py`

**Cambios exactos:**

1. El campo `georef` en el response de `/invert` agrega:
```python
"georef": {
    "confidence": georef_confidence,
    "type": georef_type,
    "utm_zone": utm_zone_val,
    "utm_hemisphere": utm_hemisphere_val,  # NUEVO
    "epsg_code": epsg_code_val,             # NUEVO
    "input_crs": input_crs_val,             # NUEVO
    "crs_source": crs_source_val,           # NUEVO
    "crs_confidence": crs_confidence_val,   # NUEVO
    "warnings": georef_warnings,
    "footprint": footprint_dict,
}
```

2. El response de `/preview` agrega los mismos campos a `georef_preview`.

3. Warning específico cuando UTM detectado y zona no declarada:
```
"UTM detectado. Para mejorar la precisión del footprint, declare la zona UTM en el campo 
'utm_zone' del formulario de inversión (ej: '19S', '33N'). EPSG será calculado automáticamente."
```

**Criterios de aceptación R2-BE-5:**
- [ ] Response de `/invert` tiene campos nuevos `utm_hemisphere`, `epsg_code`, `input_crs`, `crs_source`, `crs_confidence` en el objeto `georef`.
- [ ] Response de `/preview` tiene `georef_preview.epsg_code` (null si no declarado).
- [ ] Warning de UTM sin zona aparece cuando el sistema detecta UTM y `utm_zone_form` es null.

---

### R2-BE-6 — Tests geodésicos

**Archivos en scope:**
- Nuevo: `terraquantum-backend/tests/test_r2_crs_utm.py`
- Nuevo: `terraquantum-backend/tests/test_r2_epsg_lookup.py`

**Tests requeridos:**

```python
# test_r2_epsg_lookup.py
def test_epsg_from_utm_zone_19S():
    assert get_epsg_from_utm(19, "S") == 32719

def test_epsg_from_utm_zone_19N():
    assert get_epsg_from_utm(19, "N") == 32619

def test_epsg_from_utm_zone_1N():
    assert get_epsg_from_utm(1, "N") == 32601

def test_epsg_from_utm_zone_60S():
    assert get_epsg_from_utm(60, "S") == 32760

def test_epsg_from_utm_invalid_zone_raises():
    with pytest.raises(ValueError):
        get_epsg_from_utm(0, "N")
    with pytest.raises(ValueError):
        get_epsg_from_utm(61, "S")

def test_epsg_from_utm_invalid_hemisphere_raises():
    with pytest.raises(ValueError):
        get_epsg_from_utm(19, "X")

# test_r2_crs_utm.py
def test_parse_utm_zone_string_south():
    n, h = parse_utm_zone_string("19S")
    assert n == 19 and h == "S"

def test_parse_utm_zone_string_north():
    n, h = parse_utm_zone_string("33N")
    assert n == 33 and h == "N"

def test_parse_utm_zone_string_lowercase():
    n, h = parse_utm_zone_string("19s")
    assert n == 19 and h == "S"

def test_parse_utm_zone_string_invalid():
    with pytest.raises(ValueError):
        parse_utm_zone_string("zona_invalida")
    with pytest.raises(ValueError):
        parse_utm_zone_string("99S")  # zona > 60

def test_validate_utm_easting_out_of_range():
    warns = validate_utm_easting_northing(50_000, 5_000_000, 19, "N")
    assert any("easting" in w.lower() for w in warns)

def test_validate_utm_easting_in_range():
    warns = validate_utm_easting_northing(580_000, 5_650_000, 19, "N")
    assert warns == []

def test_classify_georef_with_utm_zone_declared():
    # Usuario declara utm_zone="19S" → crs_source="user_declared", epsg=32719
    ...

def test_r1_tests_still_pass():
    # Marcador: los tests de R1 no deben romper
    # (se ejecutan en la misma suite automáticamente)
    pass
```

**Criterios de aceptación R2-BE-6:**
- [ ] `python -m pytest tests/test_r2_epsg_lookup.py tests/test_r2_crs_utm.py -v` pasa sin errores.
- [ ] `python -m pytest tests/test_r1_georef_contract.py tests/test_r1_footprint_endpoint.py -v` sigue pasando.
- [ ] `python -m pytest tests/ -v` pasa (todas las suites).

---

## 8. Frontend plan

### R2-FE-1 — Campos UI para CRS/UTM en formulario de importación

**Archivos en scope:**
- `terraquantum-web/componentes/GravityCsvPreviewPanel.tsx`

**Cambios exactos:**

El panel de preview muestra `georef_preview.confidence`. Cuando `georef_preview.confidence = "MEDIUM"` y el sistema detectó UTM (`georef_preview.type = "csv_utm"`):
1. Mostrar sección "Declaración de Zona UTM" con:
   - Input de texto para zona UTM (ej. "19S"). Placeholder: "ej: 19S, 33N".
   - Selector hemisferio N/S (deshabilitado si la letra está en la zona).
   - EPSG derivado (readonly, calculado en frontend desde zona + hemisferio).
2. Esta sección aparece también en el formulario de inversión para pasarla como `utm_zone` al backend.

```typescript
// Componente de campo UTM (dentro de GravityCsvPreviewPanel)
// Solo aparece cuando georef_preview.type === "csv_utm"

const [utmZone, setUtmZone] = useState<string>("");
const derivedEpsg = useMemo(() => {
  const match = utmZone.trim().toUpperCase().match(/^(\d{1,2})([NS])$/);
  if (!match) return null;
  const zone = parseInt(match[1]);
  const hemi = match[2];
  if (zone < 1 || zone > 60) return null;
  return hemi === "N" ? 32600 + zone : 32700 + zone;
}, [utmZone]);
```

**Criterios de aceptación R2-FE-1:**
- [ ] Cuando preview detecta UTM, aparece campo "Zona UTM".
- [ ] Al escribir "19S", el EPSG derivado muestra "EPSG:32719".
- [ ] El campo se pasa como `utm_zone` al formulario de inversión.
- [ ] `cmd /c npx eslint componentes/GravityCsvPreviewPanel.tsx` sin errores.

---

### R2-FE-2 — Validación de formulario UTM

**Archivos en scope:**
- `terraquantum-web/componentes/GravityCsvPreviewPanel.tsx`

**Validación:**
- Formato aceptado: `/^\d{1,2}[NnSs]$/` → "19S", "3n", "60S".
- Zona fuera de rango (0 o >60): error "Zona UTM inválida (1-60)".
- Campo vacío: válido (zona es opcional en R2, solo warning).
- El campo no bloquea la inversión — solo agrega información si está lleno.

**Criterios de aceptación R2-FE-2:**
- [ ] "19S" → válido, EPSG 32719 mostrado.
- [ ] "99S" → error "Zona UTM inválida".
- [ ] "" → válido (sin zona declarada, inversión procede con warnings).
- [ ] `cmd /c npx eslint` sin errores.

---

### R2-FE-3 — Badges CRS

**Archivos en scope:**
- `terraquantum-web/componentes/huds/GeoDashboard.tsx`
- `terraquantum-web/lib/terraquantum/frontendApi.ts`

**Cambios en `frontendApi.ts`:**

```typescript
// AGREGAR tipos CRS R2:
export type CrsSource = "user_declared" | "csv_column" | "inferred" | "missing";
export type CrsConfidence = "HIGH" | "MEDIUM" | "LOW" | "MISSING";

export type CrsInfo = {
  input_crs: string | null;
  epsg_code: number | null;
  crs_source: CrsSource;
  crs_confidence: CrsConfidence;
  utm_zone: string | null;
  utm_hemisphere: string | null;
};
```

**Cambios en `GeoDashboard.tsx`:**
- Agregar badge `crs_source` junto al badge `georef_confidence` existente.
- Mostrar EPSG code si está disponible: "CRS Input: EPSG:32719".
- Si `epsg_code = null`: "CRS Input: Desconocido".

**Badge labels para crs_source:**
```
user_declared → "CRS Declarado" (verde)
csv_column    → "CRS del CSV"   (verde)
inferred      → "CRS Inferido"  (amarillo)
missing       → "CRS Desconocido" (rojo)
```

**Criterios de aceptación R2-FE-3:**
- [ ] GeoDashboard muestra badge crs_source.
- [ ] EPSG code visible cuando disponible.
- [ ] `cmd /c npx eslint componentes/huds/GeoDashboard.tsx` sin errores.

---

### R2-FE-4 — Historial/reportes

**Archivos en scope:**
- `terraquantum-web/componentes/datos/ProjectRunList.tsx`
- `terraquantum-web/store/useAppStore.ts`

**Cambios en `useAppStore.ts`:**

```typescript
// AGREGAR a AppState (R2):
crsInfo: CrsInfo | null;
setCrsInfo: (info: CrsInfo | null) => void;
```

**Cambios en `ProjectRunList.tsx`:**
- Mostrar EPSG code por proyecto en la lista (si disponible).
- Tooltip: "Zona UTM: {utm_zone} | EPSG: {epsg_code}".
- Si EPSG null: tooltip "CRS desconocido — declarar zona UTM en próxima inversión".

**Criterios de aceptación R2-FE-4:**
- [ ] Lista de proyectos muestra EPSG code cuando disponible.
- [ ] `cmd /c npx eslint componentes/datos/ProjectRunList.tsx store/useAppStore.ts` sin errores.

---

## 9. Tests automáticos

### 9.1 Suite completa de tests R2

```
tests/test_r2_epsg_lookup.py        — Lookup EPSG desde zona+hemisferio (10 tests)
tests/test_r2_crs_utm.py            — Parsing zona UTM, validación rangos (8 tests)
tests/test_r2_schemas.py            — CrsContract, campos nuevos ProjectMeta/Footprint (5 tests)
tests/test_r2_invert_api.py         — /invert con utm_zone_form → epsg/input_crs en respuesta (4 tests)
tests/test_r2_classify_georef.py    — _classify_georef extendido para crs_source/crs_confidence (6 tests)
```

### 9.2 Tests de regresión R1 (no modificar)

Los siguientes tests **deben pasar sin cambios** al finalizar R2:
```
tests/test_r1_georef_contract.py
tests/test_r1_footprint_endpoint.py
tests/test_r1_report_georef.py
tests/test_geo_utils.py
tests/test_coordinate_transform.py
tests/test_project_geospatial.py
```

Ejecutar antes de cualquier commit R2:
```bash
python -m pytest tests/test_r1_georef_contract.py tests/test_r1_footprint_endpoint.py tests/test_r1_report_georef.py tests/test_geo_utils.py tests/test_coordinate_transform.py -v
```

### 9.3 Criterio de cierre de tests R2

```bash
python -m pytest tests/ -v
# → PASS en todos los tests R1 + R2
# → Sin errores de import
# → Sin warnings de deprecación de Pydantic
```

---

## 10. QA manual

### QA-R2-1: CSV UTM + zona declarada en UI

**Dataset:** CSV con columnas `x_m`, `z_m` (valores de easting UTM > 100,000) + ancla lat/lon.  
**Acción:** En campo "Zona UTM" del formulario, escribir "19S".  
**Expectativa:**
- EPSG derivado en UI: "EPSG:32719".
- Response de `/invert` tiene `georef.epsg_code = 32719`, `georef.utm_zone = "19S"`, `georef.crs_source = "user_declared"`.
- `project_meta.json` tiene `input_crs = "EPSG:32719"` (no "EPSG:4326").
- Badge crs_source en GeoDashboard: "CRS Declarado" (verde).

### QA-R2-2: CSV UTM sin zona declarada

**Dataset:** Mismo CSV, sin llenar campo zona.  
**Expectativa:**
- Warning en UI: "UTM detectado sin zona. Declare zona para mejorar precisión."
- Response de `/invert` tiene `georef.utm_zone = null`, `georef.epsg_code = null`, `georef.crs_source = "missing"`.
- `project_meta.json` tiene `input_crs = "unknown"` (no "EPSG:4326").
- Badge crs_source: "CRS Desconocido" (rojo).

### QA-R2-3: CSV lat/lon estaciones

**Dataset:** CSV con columnas `lat`, `lon`, `g`.  
**Expectativa:**
- `georef.input_crs = "EPSG:4326"`, `georef.epsg_code = 4326`, `georef.crs_source = "inferred"`.
- `georef.crs_confidence = "HIGH"`.
- Sin campo UTM zone en UI (no aplica).
- Badge crs_source: "CRS Inferido" (amarillo).

### QA-R2-4: Zona UTM inválida en formulario

**Acción:** Escribir "99S" en campo zona.  
**Expectativa:**
- Validación frontend: error "Zona UTM inválida (1-60)".
- No se envía al backend.
- Campo no bloquea el resto del formulario.

### QA-R2-5: CSV metros locales (HVC real)

**Dataset:** HVC CSV (`CORE-REAL-9_source_gravity_HVC_fixed.csv`) + lat=-22.28, lon=-68.89.  
**Expectativa:**
- `georef.input_crs = "local_meters"`, `georef.epsg_code = null`, `georef.crs_source = "missing"`.
- Warning: "Metros locales sin CRS definido."
- Badge crs_source: "CRS Desconocido" (rojo).
- `georef_confidence` y footprint: sin cambio de R1 (LOW, local_meters_anchored).

### QA-R2-6: Verificación de no-regresión R1

**Acción:** Ejecutar QA-1 a QA-5 de R1 (ver R1 spec Sección 13) sin modificar datasets.  
**Expectativa:**
- Todos los resultados de R1 se mantienen.
- Campos nuevos de R2 aparecen en los responses pero no rompen ningún flujo existente.

---

## 11. Riesgos

### R2-RIESGO-1 — PATCH endpoint destruye footprint (BUG de R1, crítico para R2)

**Descripción:** `PATCH /projects/{project_id}` (línea 183-204 de `project_api.py`) reconstruye `ProjectMeta` desde cero. Sobrescribe `footprint`, `georef_confidence`, `utm_zone`, etc. con valores por defecto. Un PATCH simple de latitud destruye el CRS contract que R2 guarda.

**Severidad:** ALTA — afecta persistencia de datos R2.

**Mitigación requerida ANTES de R2:** Modificar el PATCH para hacer merge con el meta existente en lugar de reconstruir desde cero. Esta corrección es pequeña y aislada.

```python
# CORRECCIÓN propuesta para project_api.py PATCH:
@router.patch("/{project_id}", response_model=ProjectResponse)
async def update_project(project_id: str, req: ProjectUpdate):
    ...
    existing = load_project_meta(project_id) or {}
    now = utc_now_iso()
    # Merge: actualizar solo los campos de ProjectUpdate, preservar todo lo demás
    merged = dict(existing)
    if req.latitude is not None:
        merged["latitude"] = req.latitude
    if req.longitude is not None:
        merged["longitude"] = req.longitude
    if req.crs is not None:
        merged["crs"] = req.crs
    merged["updated_at"] = now
    save_project_meta(project_id, merged)
    return build_project_response(project_id, merged)
```

### R2-RIESGO-2 — pyproj en Windows: instalación no verificada

**Descripción:** pyproj>=3.6 distribuye wheels pre-compilados para Windows x64 via PyPI. Debería funcionar con `pip install pyproj` sin compilar desde fuente. Sin embargo, no está verificado en el entorno Windows 11 del desarrollador.

**Severidad:** MEDIA para R2.2 (no aplica a R2.0 con Opción C).

**Mitigación:** Verificar antes de R2.2:
```
pip install pyproj>=3.6.0
python -c "from pyproj import Transformer; print('OK')"
```
Si falla, usar conda: `conda install -c conda-forge pyproj`.

### R2-RIESGO-3 — Zona UTM inferida incorrectamente por usuario

**Descripción:** Si el usuario declara zona incorrecta (ej. "18S" en lugar de "19S"), el sistema acepta la declaración como `crs_source="user_declared"`, `crs_confidence="HIGH"`. El footprint calculado puede tener desplazamiento significativo si la zona incorrecta tiene offset de 500km+ en easting.

**Severidad:** MEDIA.

**Mitigación R2:** Validar que easting/northing estén dentro del rango válido para la zona declarada. Warning automático cuando hay discrepancia. No bloquear — el sistema no puede saber con certeza cuál zona es la correcta sin pyproj.

**Mitigación R2.2:** Con pyproj, verificar que la transformación UTM→WGS84 produzca una lat/lon "razonable" comparada con el lat/lon central del usuario.

### R2-RIESGO-4 — CSV con columna "zone" con formato no estándar

**Descripción:** El parser R2 lee columna `zone`. Pero los formatos pueden variar: "19S", "19 S", "zone 19 south", "UTM-19S", "EPSG:32719".

**Severidad:** BAJA.

**Mitigación:** El parser intenta extraer número + hemisferio con regex permisivo. Si falla, `crs_source = "missing"` y warning: "Columna 'zone' detectada pero formato no reconocido: '{valor}'. Declare zona manualmente."

### R2-RIESGO-5 — Surveys en límite de zona UTM (crossover)

**Descripción:** Un survey cerca del límite entre dos zonas UTM (ej. a 6° de longitud de separación entre zonas) puede tener coordenadas que se extienden a dos zonas. La zona declarada puede ser correcta para la mayoría de los puntos pero incorrecta para algunos.

**Severidad:** BAJA a MEDIA para R2.

**Mitigación:** Warning automático si la diferencia de longitud del survey supera 5° (≈550km, que es el ancho aproximado de una zona UTM). Para R2.2 con pyproj, detectar puntos fuera de la zona declarada.

### R2-RIESGO-6 — Compatibilidad de schemas con datos R1 legacy

**Descripción:** `project_meta.json` de proyectos existentes (guardados con R1) no tienen los campos nuevos de R2 (`input_crs`, `epsg_code`, `crs_source`, `crs_contract`). Al cargar en el endpoint, `ProjectMeta(**meta_dict)` tendrá estos campos con valores por defecto.

**Severidad:** BAJA — Pydantic usa valores por defecto para campos opcionales ausentes.

**Mitigación:** Asegurarse de que todos los campos nuevos de R2 sean `Optional` con defaults. No hay migración de datos necesaria.

---

## 12. Decisión recomendada

### 12.1 Sobre pyproj

**Decisión: Opción C — Preparar schemas y UI en R2.0, instalar pyproj en R2.2.**

Justificación:
1. Los campos `epsg_code`, `crs_source`, `utm_hemisphere`, `input_crs` tienen valor inmediato sin pyproj: corrigen el CRS guardado de "EPSG:4326" a "EPSG:32719" cuando el usuario declara la zona.
2. La función `get_epsg_from_utm()` es pura Python, sin dependencias — ya implementa el caso más común.
3. pyproj permite aislarse en un sprint dedicado (R2.2) con criterios claros de éxito: `python -c "from pyproj import Transformer; print('OK')"`.
4. Si pyproj funciona sin problemas en la instalación, se puede acelerar a R2.0. La decisión es reversible hacia Opción B.

### 12.2 Sobre UTM zone

**Decisión: Campo UI opcional + parser de columna CSV + lookup EPSG.**

El usuario puede declarar zona en el formulario. El parser lee columna `zone` si existe. La zona se valida con rangos de easting/northing. No se requiere pyproj para el lookup EPSG.

### 12.3 Sobre bloqueo de datasets sin CRS

**Decisión: No bloquear en R2. Solo advertir con badges y warnings.**

El bloqueo de inversión requiere política minera formal sobre calidad mínima de datos. R2 establece los criterios; R4+ implementa el bloqueo. El objetivo de R2 es honestidad técnica, no restricción de flujo.

### 12.4 Sobre CRS guardado

**Decisión: Corregir `input_crs` en project_meta.json para que refleje el CRS real del input.**

El campo `crs` existente (siempre "EPSG:4326") representa el CRS del output geográfico (footprint en WGS84). El nuevo campo `input_crs` representa el CRS del CSV de entrada. No hay contradicción — son dos campos con significados distintos.

### 12.5 Orden de ejecución R2

```
Pre-R2:
  FIX — PATCH endpoint no destruye footprint

R2.0 Backend (2-3 días):
  R2-BE-1 — Schemas CRS (30-45 min)
  R2-BE-2 — Parser UTM zone / EPSG lookup / coordinate_transform_real.py (90 min)
  R2-BE-4 — coordinate_transform_service actualizado (45 min)
  R2-BE-5 — gravity_import_api response actualizado (45 min)
  R2-BE-6 — Tests geodésicos (90 min)

R2.0 Frontend (1-2 días):
  R2-FE-1 — Campo UTM zone en formulario (60 min)
  R2-FE-2 — Validación de formulario (30 min)
  R2-FE-3 — Badges CRS (45 min)
  R2-FE-4 — Historial EPSG code (30 min)

R2-QA (1 día):
  QA-R2-1 a QA-R2-6

R2.2 (sprint separado, 1 día):
  R2-BE-3 — pyproj integration (si verificado en Windows y Docker)
  Tests de transformación real con tolerancia en metros
```

---

## 13. Prompts de ejecución sugeridos

### Prompt R2-BE-1 — Schemas CRS

```
Rol: Arquitecto backend Python/FastAPI. TerraQuantum.

Contexto:
- R1 está completado. Los schemas en project_schema.py ya tienen ProjectFootprint con R1 completo.
- gravity_import_schema.py tiene CoordSystemDetection y CoordinateTransform.
- R2 agrega el concepto "CrsContract" y campos de CRS a schemas existentes.

Tarea: Modificar schemas para R2 CRS.

Archivos permitidos:
- terraquantum-backend/schemas/project_schema.py
- terraquantum-backend/schemas/gravity_import_schema.py

Archivos prohibidos: Ningún otro. NO tocar APIs. NO tocar servicios.

Cambios exactos en project_schema.py:
1. Crear clase CrsContract(BaseModel) con campos:
   - input_crs: Optional[str] = None
   - output_crs: str = "EPSG:4326"
   - horizontal_datum: Optional[str] = None
   - vertical_datum: Optional[str] = None
   - utm_zone: Optional[str] = None
   - utm_hemisphere: Optional[str] = None
   - epsg_code: Optional[int] = None
   - crs_source: str = "missing"
   - crs_confidence: str = "MISSING"

2. En ProjectFootprint, agregar campos opcionales:
   - utm_hemisphere: Optional[str] = None
   - epsg_code: Optional[int] = None
   - crs_source: str = "missing"
   - crs_confidence: str = "MISSING"

3. En ProjectMeta, agregar campos opcionales:
   - input_crs: Optional[str] = None
   - epsg_code: Optional[int] = None
   - crs_source: str = "missing"
   - utm_hemisphere: Optional[str] = None
   - horizontal_datum: Optional[str] = None
   - crs_contract: Optional[CrsContract] = None

Cambios exactos en gravity_import_schema.py:
1. En CoordSystemDetection, agregar campos:
   - utm_zone: Optional[str] = None
   - utm_hemisphere: Optional[str] = None
   - epsg_code: Optional[int] = None
   - crs_source: str = "missing"

2. En CoordinateTransform, agregar campos:
   - utm_zone: Optional[str] = None
   - utm_hemisphere: Optional[str] = None
   - epsg_code: Optional[int] = None
   - crs_source: str = "missing"

Validación:
- python -m compileall schemas/project_schema.py schemas/gravity_import_schema.py
- python -m pytest tests/test_r1_georef_contract.py tests/test_r1_footprint_endpoint.py -v (deben pasar sin cambios)

Respuesta final obligatoria:
1. Archivos modificados.
2. Cambios aplicados: lista exacta.
3. python -m compileall → resultado.
4. Tests R1 → resultado.
5. Qué NO se tocó.
6. Riesgos pendientes.
```

---

### Prompt R2-BE-2 — Parser/metadata para UTM zone/EPSG

```
Rol: Arquitecto backend Python/FastAPI. TerraQuantum.

Contexto:
- R2-BE-1 completado. Schemas tienen CrsContract y campos CRS.
- _classify_georef() en gravity_import_api.py siempre retorna utm_zone=None (hardcoded).
- No existe función para calcular EPSG desde zona+hemisferio.
- El endpoint /invert no acepta parámetro utm_zone del formulario.

Tarea: Agregar EPSG lookup y parser UTM zone.

Archivos permitidos:
- terraquantum-backend/services/coordinate_transform_real.py (NUEVO)
- terraquantum-backend/api/gravity_import_api.py

Archivos prohibidos: NO tocar project_api.py. NO tocar schemas. NO tocar coordinate_transform_service.py.

Cambios exactos:

1. Crear services/coordinate_transform_real.py con:

   def get_epsg_from_utm(zone_number: int, hemisphere: str) -> int:
       """UTM Norte: 32600+zona, Sur: 32700+zona. Zona 1-60."""
       n = int(zone_number)
       if not (1 <= n <= 60):
           raise ValueError(f"Número de zona UTM inválido: {n}. Debe ser 1-60.")
       h = hemisphere.upper()
       if h == "N":
           return 32600 + n
       if h == "S":
           return 32700 + n
       raise ValueError(f"Hemisferio inválido: {hemisphere}. Debe ser 'N' o 'S'.")
   
   def parse_utm_zone_string(zone_str: str) -> tuple[int, str]:
       """Parsea '19S' → (19, 'S'). Lanza ValueError si inválido."""
       import re
       m = re.match(r'^(\d{1,2})\s*([NnSs])$', zone_str.strip())
       if not m:
           raise ValueError(f"Formato de zona UTM inválido: '{zone_str}'. Usar '19S' o '33N'.")
       n = int(m.group(1))
       h = m.group(2).upper()
       if not (1 <= n <= 60):
           raise ValueError(f"Número de zona UTM inválido: {n}. Debe ser 1-60.")
       return n, h
   
   def validate_utm_easting_northing(
       easting: float, northing: float, zone_num: int, hemisphere: str
   ) -> list[str]:
       """Retorna lista de warnings si easting/northing están fuera de rango UTM válido."""
       warns = []
       if not (100_000 <= easting <= 900_000):
           warns.append(
               f"Easting {easting:.0f} m fuera del rango válido UTM (100,000–900,000 m). "
               "Verificar zona declarada."
           )
       if hemisphere.upper() == "N" and not (0 <= northing <= 9_330_000):
           warns.append(
               f"Northing {northing:.0f} m fuera del rango válido UTM Norte (0–9,330,000 m)."
           )
       if hemisphere.upper() == "S" and not (1_000_000 <= northing <= 10_000_000):
           warns.append(
               f"Northing {northing:.0f} m fuera del rango válido UTM Sur (1,000,000–10,000,000 m)."
           )
       return warns

2. En gravity_import_api.py:
   a. Importar get_epsg_from_utm, parse_utm_zone_string, validate_utm_easting_northing desde services.coordinate_transform_real.
   b. En endpoint /invert, agregar parámetro: utm_zone_form: Optional[str] = Form(None)
   c. Modificar _classify_georef() para aceptar: utm_zone_form: Optional[str] = None
      - Si utm_zone_form provisto: parse_utm_zone_string() → utm_zone, utm_hemisphere, epsg_code, crs_source="user_declared"
      - Si falla el parse: warning + crs_source="missing"
      - Retornar crs_source, crs_confidence, utm_hemisphere, epsg_code, input_crs adicionales
   d. Actualizar project_meta.json para incluir: input_crs, epsg_code, crs_source, utm_hemisphere.
   e. Actualizar georef dict en response con los nuevos campos.

Validación:
- python -m compileall services/coordinate_transform_real.py api/gravity_import_api.py
- python -m pytest tests/test_r1_georef_contract.py tests/test_r1_footprint_endpoint.py -v (deben pasar)

Respuesta final obligatoria:
1. Archivos creados/modificados.
2. Cambios exactos.
3. Compilación.
4. Tests R1 pasan.
5. Qué NO se tocó.
6. Riesgos.
```

---

### Prompt R2-BE-3 — pyproj (solo para R2.2, ejecutar después de verificar instalación)

```
Rol: Arquitecto backend Python/FastAPI. TerraQuantum.

PREREQUESITE OBLIGATORIO antes de ejecutar este prompt:
Verificar en el entorno del desarrollador:
  pip install pyproj>=3.6.0
  python -c "from pyproj import Transformer; print('OK')"
Si falla: NO ejecutar este prompt. Usar conda install -c conda-forge pyproj y repetir.

Contexto:
- R2-BE-1 y R2-BE-2 completados.
- services/coordinate_transform_real.py existe con stub NotImplementedError.
- pyproj está instalado y verificado en Windows y Docker.

Tarea: Reemplazar stub con implementación real usando pyproj.

Archivos permitidos:
- terraquantum-backend/services/coordinate_transform_real.py
- terraquantum-backend/requirements.txt

Archivos prohibidos: NO tocar gravity_import_api.py. NO tocar schemas. NO tocar solver.

Cambios exactos:

1. En requirements.txt, agregar: pyproj>=3.6.0

2. En coordinate_transform_real.py, reemplazar stub transform_utm_to_wgs84 con:
   from pyproj import Transformer
   
   def transform_utm_to_wgs84(easting: float, northing: float, epsg_code: int) -> tuple[float, float]:
       t = Transformer.from_crs(f"EPSG:{epsg_code}", "EPSG:4326", always_xy=True)
       lon, lat = t.transform(easting, northing)
       return lat, lon
   
   def transform_latlon_to_utm(lat: float, lon: float, epsg_code: int) -> tuple[float, float]:
       t = Transformer.from_crs("EPSG:4326", f"EPSG:{epsg_code}", always_xy=True)
       easting, northing = t.transform(lon, lat)
       return easting, northing

Validación:
- python -c "from services.coordinate_transform_real import transform_utm_to_wgs84; print(transform_utm_to_wgs84(580000, 5650000, 32619))"
  → Resultado esperado: lat≈51.0°N, lon≈-78°W (zona 19N, ejemplo Quebec-Ontario)
- python -m pytest tests/ -v (todos los tests pasan)
- docker build . → imagen construye sin error
- docker run ... python -c "from pyproj import Transformer; print('OK')"

Respuesta final obligatoria:
1. Archivos modificados.
2. Output de transform_utm_to_wgs84 test.
3. Tests completos.
4. Docker build resultado.
5. Qué NO se tocó.
6. Riesgos.
```

---

### Prompt R2-FE-1 — Campo UTM zone en formulario

```
Rol: Arquitecto frontend React/TypeScript/Next.js. TerraQuantum.

Contexto:
- R2 backend completado. /invert acepta utm_zone_form.
- GravityCsvPreviewPanel.tsx muestra georef_preview del backend.
- Cuando georef_preview.type === "csv_utm": el usuario debería poder declarar zona UTM.
- No existe campo UI para zona UTM en ningún componente.

Tarea: Agregar campo UTM zone al panel de importación.

Archivos permitidos:
- terraquantum-web/componentes/GravityCsvPreviewPanel.tsx
- terraquantum-web/lib/terraquantum/frontendApi.ts

Archivos prohibidos: NO tocar Scene3D. NO tocar solver. NO tocar otros componentes.

Cambios en frontendApi.ts:
1. Agregar tipos CRS R2:
   export type CrsSource = "user_declared" | "csv_column" | "inferred" | "missing";
   export type CrsConfidence = "HIGH" | "MEDIUM" | "LOW" | "MISSING";
   export type CrsInfo = {
     input_crs: string | null;
     epsg_code: number | null;
     crs_source: CrsSource;
     crs_confidence: CrsConfidence;
     utm_zone: string | null;
     utm_hemisphere: string | null;
   };

Cambios en GravityCsvPreviewPanel.tsx:
1. Agregar estado: const [utmZone, setUtmZone] = useState<string>("");
2. Calcular EPSG derivado con useMemo:
   - Regex /^(\d{1,2})([NnSs])$/ sobre utmZone.trim()
   - Norte: 32600 + zona, Sur: 32700 + zona
   - null si formato inválido o zona fuera de 1-60
3. Mostrar sección "Zona UTM" SOLO cuando georef_preview?.type === "csv_utm":
   - Input text "Zona UTM" con placeholder "ej: 19S, 33N"
   - Mostrar EPSG derivado (readonly): "EPSG:{numero}" o "Formato inválido"
   - Validación inline: zona 0 o >60 → "Zona UTM inválida (1-60)"
4. Pasar utmZone al formulario de inversión (campo utm_zone en FormData).

Validación:
- cmd /c npx eslint componentes/GravityCsvPreviewPanel.tsx lib/terraquantum/frontendApi.ts
- Sin errores TypeScript.

Respuesta final obligatoria:
1. Archivos modificados.
2. Cambios exactos.
3. Resultado ESLint.
4. Qué NO se tocó.
5. Riesgos.
```

---

### Prompt R2-QA — QA manual completo

```
Rol: QA engineer de TerraQuantum. R2 backend y frontend completados.

Contexto:
- Backend corriendo en localhost:8010
- Frontend corriendo en localhost:3000
- R2-BE-1 a R2-BE-6 completados
- R2-FE-1 a R2-FE-4 completados

Tarea: Ejecutar QA manual de R2 con los 6 casos definidos.

NO modificar ningún archivo. Solo observar, verificar y reportar.

Para cada caso (ver Sección 10 del spec R2):
1. Ejecutar la acción.
2. Verificar el resultado esperado campo por campo.
3. Reportar PASS o FAIL con evidencia exacta.

Casos:
QA-R2-1: CSV UTM + zona "19S" declarada en UI
  - Verificar: epsg_code=32719, crs_source="user_declared", input_crs="EPSG:32719"
QA-R2-2: CSV UTM sin zona
  - Verificar: utm_zone=null, epsg_code=null, crs_source="missing", input_crs="unknown"
QA-R2-3: CSV lat/lon estaciones
  - Verificar: input_crs="EPSG:4326", epsg_code=4326, crs_source="inferred"
QA-R2-4: Zona "99S" en formulario
  - Verificar: error de validación en UI, no se envía al backend
QA-R2-5: HVC CSV metros locales
  - Verificar: input_crs="local_meters", epsg_code=null, crs_source="missing"
QA-R2-6: No-regresión R1
  - Verificar: georef_confidence sigue siendo correcto para lat/lon y local_meters

Respuesta final obligatoria:
1. QA-R2-1: PASS/FAIL + evidencia.
2. QA-R2-2: PASS/FAIL + evidencia.
3. QA-R2-3: PASS/FAIL + evidencia.
4. QA-R2-4: PASS/FAIL + evidencia.
5. QA-R2-5: PASS/FAIL + evidencia.
6. QA-R2-6: PASS/FAIL + evidencia.
7. Tests automáticos: python -m pytest tests/ -v → resultado.
8. Confirmación de que NO se modificó ningún archivo.
```

---

*Fin de la especificación R2.*

*Próxima fase: R3 — Elevación absoluta de voxels, DEM co-registrado con footprint real, host volume siguiendo topografía.*  
*Este documento NO reemplaza R1_SPATIAL_CONTRACT_SPEC.md ni la INDUSTRIAL_REALITY_BIBLE.md — los complementa para la fase R2.*
