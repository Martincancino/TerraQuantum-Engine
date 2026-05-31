# TERRAQUANTUM — R3.5 INDUSTRIAL INPUT CONTRACT SPEC
## Contrato de Entrada Industrial para CSV de Gravimetría
**Versión:** 1.0.0  
**Fecha:** 2026-05-20  
**Estado:** SPEC APROBADA — pendiente implementación  
**Autor:** Auditoría arquitectónica R3.5 (Claude Code — geophysics architect mode)  
**Prerrequisitos:** R1 (Footprint), R2 (CRS/pyproj), R3 (DEM/elevación)

---

## GLOSARIO RÁPIDO

| Término | Definición |
|---------|-----------|
| `spatial_readiness_level` | Nivel 0–5 que describe la suficiencia espacial del CSV para inversión 3D |
| `georef_confidence` | Concepto R1/R2: calidad de la georreferencia (HIGH/MEDIUM/LOW/MISSING) — distinto de spatial readiness |
| `can_run_3d_inversion` | Booleano que el hard gate emite; bloquea o permite el solver |
| `SpatialReadiness` | Nuevo schema Pydantic con los 6 campos del contrato |
| Hard Gate | Condición de bloqueo verificada ANTES de llamar al solver |
| Anchor | Par lat/lon declarado por el usuario para georreferenciar modelo local |

---

## SECCIÓN 1 — DICTAMEN PRINCIPAL

### 1.1 Veredicto de la Auditoría

**VEREDICTO: SISTEMA INCOMPLETO — RIESGO INDUSTRIAL ALTO**

TerraQuantum tiene hoy un pipeline de inversión 3D que:

1. **Acepta CSVs sin coordenadas reales** y produce modelos 3D que aparentan tener ubicación geográfica
2. **Calcula favorabilidad HIGH** incluso cuando `georef_confidence = MISSING`
3. **No tiene ningún gate de bloqueo** entre la validación de formato CSV y la ejecución del solver
4. **No comunica al usuario** que el modelo producido es conceptual, no georeferenciado ni comparable con datos de terceros
5. **Permite priority_class = HIGH** en proyectos sin coordenadas reales

Para uso en laboratorio académico o demostrativo: aceptable con advertencias.  
Para entrega a una minera real: **inaceptable sin este contrato implementado**.

### 1.2 Principio Rector del Contrato

> *"Si el CSV no aporta suficiente información espacial para posicionar el modelo en la Tierra real, el sistema DEBE decírselo al usuario con claridad y DEBE bloquear cualquier output que implique ubicación geográfica verdadera."*

### 1.3 Qué resuelve este documento

Este documento especifica:
- El contrato mínimo de entrada que debe cumplir un CSV de gravimetría
- Los niveles de suficiencia espacial (LEVEL 0–5)
- Los campos mínimos requeridos por nivel
- Los hard gates de bloqueo en el backend
- Los cambios de UI requeridos para comunicar restricciones
- Los cambios en reportes para no mentir sobre ubicación
- El plan de implementación en subfases

---

## SECCIÓN 2 — PROBLEMA ACTUAL

### 2.1 El problema de raíz

El parser actual (`gravity_import_service.py`) exige columnas `x_m`, `y_m`, `z_m` y una columna de gravedad. Esto asegura que **el CSV tenga formato** correcto, pero NO asegura que las coordenadas tengan significado geográfico real.

### 2.2 Árbol de decisión actual (sin gates)

```
CSV ingresado
    ↓
¿Columnas requeridas presentes? (x_m, y_m, z_m, gravity)
    ├── NO → error 422
    └── SÍ
        ↓
¿≥ 10 observaciones válidas?
    ├── NO → error "INSUFICIENTE"
    └── SÍ
        ↓
¿Gravity ≈ 0?
    ├── SÍ → error "zero gravity"
    └── NO
        ↓
[ INVERSION RUNS — sin importar si x,z son coordenadas reales ]
        ↓
Modelo 3D producido con footprint posiblemente MISSING
        ↓
Favorability score posiblemente HIGH
        ↓
Report HTML generado sin advertencia de georef insuficiente
```

### 2.3 Escenarios de falla identificados

| Escenario | Qué pasa hoy | Qué debería pasar |
|-----------|-------------|-------------------|
| CSV sin lat/lon, x/z = 0–500 (local) | `georef=MISSING`, inversión corre | Bloquear inversión o exigir anchor |
| CSV UTM sin zona declarada | `georef=MEDIUM`, `utm_zone=None`, inversión corre | Exigir declaración de zona |
| CSV con lat/lon válidas | `georef=HIGH`, inversión corre correctamente | ✓ Correcto |
| CSV solo gravity, x/z copiadas | `georef=MISSING`, inversión corre, favorability puede ser HIGH | Bloquear y advertir |
| CSV con corrección Bouguer pero sin elevación DEM | DEM no enriquece la inversión | Advertir, no bloquear |

### 2.4 Brechas confirmadas por código auditado

| Brecha | Archivo | Línea aprox. |
|--------|---------|-------------|
| Sin gate espacial pre-inversion | `gravity_import_api.py` | ~L465 (entre import_result y run_geophysics_inversion) |
| Favorability sin cap espacial | `favorability_service.py` | `compute_favorability_score()` — no recibe spatial_level |
| Frontend sin bloqueo en botón Invertir | `GravityCsvPreviewPanel.tsx` | ~L120 (submit handler) |
| Sin `SpatialReadiness` en store | `useAppStore.ts` | `GeoReportInfo` interface |
| Sin tipo `SpatialReadiness` en API client | `frontendApi.ts` | Sin type |
| Report HTML sin sección de georef insuficiente | `report_generator.py` | `_georef_section_html()` solo muestra nivel, no bloquea lenguaje |

---

## SECCIÓN 3 — QUÉ CSV PUEDE ENTREGAR UNA MINERA REAL

### 3.1 Taxonomía de CSVs del mundo real

Una empresa minera o de exploración puede entregar cualquiera de estos:

#### Tipo A — Levantamiento profesional completo
```
station_id, lat, lon, elevation_masl, gravity_anomaly, uncertainty, instrument_id, survey_date
ST001, -28.341, -70.542, 1823.4, -45.23, 0.01, CG-6, 2024-03-15
```
- Tiene: coordenadas absolutas, elevación MASL, incertidumbre, metadata de instrumento
- Requiere: transformar lat/lon a metros locales para el solver
- Georef: puede ser HIGH si extent < 100km

#### Tipo B — UTM con zona conocida
```
station_id, easting, northing, elevation_masl, g_corrected
ST001, 357432.1, 6871234.5, 1823.4, -45.23
```
- Tiene: UTM easting/northing, elevación MASL
- NO tiene: `lat`/`lon` en columnas, pero es georreferenciable con zona
- Georef: MEDIUM→HIGH si zona UTM se declara

#### Tipo C — UTM sin zona
```
station_id, x, y, z, gravity
ST001, 357432.1, 1823.4, 6871234.5, -45.23
```
- Tiene: valores UTM por magnitud, pero sin zona declarada
- Georef inferida: MEDIUM (detectado como `utm` por rangos)
- Riesgo: 10 zonas posibles, offset de ~100km entre zonas

#### Tipo D — Local métrico sin CRS
```
station_id, x_m, y_m, z_m, g_raw
P001, 0.0, 0.0, 0.0, -45.1
P002, 50.0, 0.0, 50.0, -44.8
```
- Tiene: coordenadas relativas, sistema propio de la campaña
- Georef: LOW (si se provee anchor) o MISSING (sin anchor)
- Uso legítimo: modelo conceptual, estudio de factibilidad interna

#### Tipo E — Solo gravedad, sin coordenadas reales
```
station_id, x_m, y_m, z_m, gravity
P001, 1, 0, 1, -45.1
P002, 2, 0, 2, -44.8
```
- x/z son índices o distancias de perfil sin referencia geográfica
- Georef: MISSING
- Uso: demostrativo/académico solamente

#### Tipo F — Perfil 2D (sin z)
```
dist_m, gravity
0.0, -45.1
50.0, -44.8
```
- No tiene formato TerraQuantum (faltan columnas required)
- Acción: error de formato en el parser — fuera de este contrato

#### Tipo G — Gravity en Bouguer con elevación implícita
```
station_id, x_m, y_m, z_m, bouguer_anomaly, terrain_correction
```
- Requiere elevación del terreno para ser válido científicamente
- Sin DEM co-registrado: inversión posible pero advertencia importante

#### Tipo H — Datos sintéticos/demo
```
gravity_type = "synthetic_demo"
```
- Caso especial: debe fluir sin gates espaciales duras
- Usar para demos y pruebas

#### Tipo I — Grid regular sin station_id
```
x_m, z_m, y_m, gravity_anomaly
0, 0, 0, -10.5
100, 0, 0, -10.3
```
- Frecuente en procesados de gabinete (interpolación Kriging, etc.)
- No tiene `station_id` — hoy bloqueado por parser

#### Tipo J — Datos de satélite (EIGEN/EGM)
```
lat, lon, free_air_anomaly
-28.341, -70.542, -12.3
```
- Resolución ~10–100 km, no útil para minería de detalle
- Debe advertir si `uncertainty` no está definido o es muy alto

### 3.2 Resumen de capacidad actual vs. requerida

| Tipo CSV | Soportado hoy | Nivel requerido | Bloqueo necesario |
|----------|--------------|-----------------|-------------------|
| A (lat/lon completo) | ✓ Parcial | LEVEL 4–5 | Ninguno si pyproj activo |
| B (UTM con zona) | ✓ Parcial | LEVEL 3–4 | Ninguno si zona declarada |
| C (UTM sin zona) | ✓ Sin gate | LEVEL 2 | Exigir zona o degradar |
| D (local + anchor) | ✓ Sin gate | LEVEL 1 | Nada si anchor presente |
| E (solo gravedad) | ✓ Sin gate | LEVEL 0 | BLOQUEAR inversión real |
| F (perfil 2D) | ✗ | N/A | Error formato |
| G (Bouguer sin DEM) | ✓ Sin advertencia | LEVEL 2–3 | Advertir DEM ausente |
| H (sintético) | ✓ | LEVEL 0 permitido | Bypass permitido |
| I (grid sin station_id) | ✗ | Fuera de scope | Error formato |
| J (satélite) | ✓ Sin advertencia | LEVEL 3 | Advertir resolución |

---

## SECCIÓN 4 — NIVELES DE SUFICIENCIA ESPACIAL (LEVEL 0–5)

### 4.1 Definición de niveles

#### LEVEL 0 — NO_SPATIAL_DATA
**Descripción:** El CSV tiene columnas de coordenadas (`x_m`, `z_m`) pero los valores no representan posiciones geográficas reales. No hay CRS, no hay anchor, no hay información suficiente para ubicar el modelo en la Tierra.

**Indicadores:**
- `coordinate_system = "local_meters"` O `coordinate_system = "unknown"`
- Sin anchor declarado (sin lat/lon del usuario)
- `georef_confidence = MISSING`
- Extent espacial imposible de determinar

**Capacidad permitida:**
- Visualización del modelo invertido en espacio relativo
- Informe de calidad interna de datos
- Análisis de gradientes y patrones de anomalía

**BLOQUEADO:**
- Inversión 3D con output georreferenciado
- Cálculo de favorabilidad con clasificación HIGH
- Reporte HTML con lenguaje de ubicación geográfica
- Priority_class = HIGH o MEDIUM

**Mensaje obligatorio al usuario:**
> "Este CSV no contiene coordenadas geográficas. Solo es posible un modelo conceptual en espacio relativo. Proporcione un punto de anclaje (lat/lon) o un CSV con coordenadas UTM/geográficas para activar la inversión georeferenciada."

---

#### LEVEL 1 — LOCAL_WITH_ANCHOR
**Descripción:** El CSV tiene coordenadas locales (metros relativos) pero el usuario ha proporcionado un punto de anclaje (lat/lon del centro o esquina SW). El modelo puede posicionarse aproximadamente en la Tierra, pero sin precisión de levantamiento.

**Indicadores:**
- `coordinate_system = "local_meters"`
- Anchor declarado (lat/lon del usuario presente)
- `georef_confidence = LOW`
- Extent inferido desde anchor + dimensiones locales

**Capacidad permitida:**
- Inversión 3D con advertencia de georef aproximado
- Footprint derivado (LOW confidence)
- Visualización con disclaimer de georef baja
- Favorability con cap en MEDIUM

**BLOQUEADO:**
- Priority_class = HIGH
- Language de ubicación precisa en reporte
- DEM co-registration (sin CRS real no hay garantía de alineación)

**Mensaje obligatorio al usuario:**
> "Modelo posicionado aproximadamente con el punto de anclaje declarado. La georeferencia es de baja confianza. No use este modelo para decisiones de sondaje sin levantamiento GPS."

---

#### LEVEL 2 — UTM_NO_ZONE
**Descripción:** El CSV tiene columnas con valores en rango UTM (100k–900k para easting, 0–10M para northing), pero no se ha declarado la zona UTM. El sistema puede inferir que es UTM pero no puede proyectar correctamente.

**Indicadores:**
- `coordinate_system = "utm"`
- `utm_zone = None` (no declarado)
- `georef_confidence = MEDIUM` (hoy) → degradar a LOW en este contrato
- Ambigüedad de ~100km entre zonas posibles

**Capacidad permitida:**
- Inversión con advertencia de zona UTM requerida
- Footprint con incertidumbre de zona
- Favorability con cap en MEDIUM

**BLOQUEADO:**
- Priority_class = HIGH
- Reporte con coordenadas absolutas
- DEM co-registration sin zona confirmada

**Acción recomendada al usuario:**
> "Se detectaron coordenadas UTM pero no se declaró la zona. Declare la zona UTM (ej: '19S') para georreferenciar correctamente el modelo. Sin zona, el offset puede ser >100 km."

---

#### LEVEL 3 — UTM_WITH_ZONE
**Descripción:** El CSV tiene UTM con zona declarada por el usuario O inferida con alta confianza. El modelo puede georreferenciarse con precisión de ~1–100m dependiendo del origen de las coordenadas.

**Indicadores:**
- `coordinate_system = "utm"`
- `utm_zone` declarado O inferido con confianza
- `crs_source = "user_declared"` O `"inferred_high_confidence"`
- `georef_confidence = MEDIUM` (sin pyproj) O `HIGH` (con pyproj)

**Capacidad permitida:**
- Inversión 3D completa
- Footprint MEDIUM–HIGH
- Favorability sin cap de spatial readiness
- Priority_class hasta HIGH si georef = HIGH
- DEM co-registration si pyproj disponible

**ADVERTENCIA:**
- Si `utm_zone` fue declarado por el usuario pero no verificado por pyproj: añadir disclaimer
- Si `crs_source = "missing"`: degradar a LEVEL 2

---

#### LEVEL 4 — GEOGRAPHIC_COORDS
**Descripción:** El CSV tiene coordenadas geográficas (lat/lon) en columnas reconocidas O en `x_m`/`z_m` con valores en rango latitudinal/longitudinal. El sistema puede usar pyproj para transformación precisa.

**Indicadores:**
- `coordinate_system = "latlon"`
- `georef_confidence = HIGH` (si extent ≤ 100km con anchor) O `MEDIUM`
- pyproj disponible para transformación

**Capacidad permitida:**
- Inversión 3D completa
- Footprint HIGH con pyproj
- Favorability completo
- Priority_class = HIGH permitido
- DEM co-registration completo
- Reporte con coordenadas absolutas

**ADVERTENCIA:**
- Si extent > 100km: advertir distorsión equirectangular (aplicable sin pyproj)
- Si columnas son `lat`/`lon` (no `x_m`/`z_m`): el parser actual NO las reconoce — BRECHA CRÍTICA

---

#### LEVEL 5 — PROFESSIONAL_SURVEY
**Descripción:** El CSV incluye coordenadas absolutas (lat/lon o UTM con zona), elevación real MASL verificable, incertidumbre por observación, identificación de instrumento, y metadata de corrección gravimétrica. Es el nivel de un levantamiento geofísico profesional.

**Indicadores:**
- `coordinate_system = "latlon"` O `"utm"` con zona
- Columna `elevation_masl` O `y_m` representando elevación real sobre nivel del mar
- `uncertainty` por observación presente
- `instrument_id` presente
- `gravity_type` = `"free_air_anomaly"` O `"bouguer_anomaly"` (no raw)
- `georef_confidence = HIGH`

**Capacidad permitida:**
- Todas las capacidades de LEVEL 4
- DEM co-registration con elevación de observación como primer candidato
- `voxel_elevation_masl` calculable con mayor precisión
- Reporte profesional completo
- Favorability con peso máximo en satellite_support si datos corresponden

**NOTA:** Este nivel activa el módulo DEM completo de R3.

### 4.2 Tabla resumen de niveles

| Level | Nombre | Coords | CRS | Elevación | Anchor | can_run_3d | max_priority |
|-------|--------|--------|-----|-----------|--------|------------|-------------|
| 0 | NO_SPATIAL_DATA | Solo locales | No | No | No | NO | NONE |
| 0* | NO_SPATIAL_DATA + anchor | Locales | No | No | Sí | CONCEPTUAL | LOW |
| 1 | LOCAL_WITH_ANCHOR | Locales | No | No | Sí | SÍ (conceptual) | MEDIUM |
| 2 | UTM_NO_ZONE | UTM | Sin zona | Posible | Opcional | SÍ (advertencia) | MEDIUM |
| 3 | UTM_WITH_ZONE | UTM | Con zona | Posible | No req | SÍ | HIGH |
| 4 | GEOGRAPHIC_COORDS | Lat/Lon | Plena | Posible | No req | SÍ | HIGH |
| 5 | PROFESSIONAL_SURVEY | Lat/Lon/UTM | Plena | MASL real | No req | SÍ | HIGH |

*LEVEL 0 con anchor = inversión conceptual permitida solo en modo DEMO_CONCEPTUAL

---

## SECCIÓN 5 — CAMPOS MÍNIMOS POR NIVEL

### 5.1 Campos del CSV requeridos por nivel

#### LEVEL 0 — NO_SPATIAL_DATA (solo modelo interno)
```
REQUIRED:
  - station_id       (o índice secuencial aceptable)
  - x_m              (cualquier valor — no interpretado como georef)
  - y_m              (elevación relativa)
  - z_m              (cualquier valor)
  - [columna gravity] (gravity_anomaly | g_corrected | g | g_raw)
  - unit             (mGal | uGal | m/s2)

FORBIDDEN implícito:
  - No puede activar: footprint, DEM, favorability HIGH, reporte con ubicación
```

#### LEVEL 1 — LOCAL_WITH_ANCHOR
```
REQUIRED (CSV):
  - Todos los de LEVEL 0

REQUIRED (del usuario en la UI):
  - anchor_lat        (latitud decimal del origen local)
  - anchor_lon        (longitud decimal del origen local)

OPTIONAL pero recomendado:
  - uncertainty
```

#### LEVEL 2 — UTM_NO_ZONE
```
REQUIRED (CSV):
  - station_id
  - x_m              (easting en metros, rango 100k–900k)
  - y_m              (elevación relativa o MASL)
  - z_m              (northing en metros, rango 0–10M)
  - [columna gravity]
  - unit

REQUIRED (del usuario si quiere LEVEL 3):
  - utm_zone         (formato: "19S", "19N", etc.)

OPTIONAL:
  - uncertainty, instrument_id
```

#### LEVEL 3 — UTM_WITH_ZONE
```
REQUIRED (CSV):
  - Todos los de LEVEL 2

REQUIRED (en form o en CSV headers/metadata):
  - utm_zone         (declarado por usuario O metadata CSV)

RECOMENDADO:
  - elevation_masl   (para DEM co-registration)
  - uncertainty
  - instrument_id
```

#### LEVEL 4 — GEOGRAPHIC_COORDS
```
REQUIRED (CSV):
  - station_id
  - lat / latitude / x_m_en_rango_latitudinal  [-90, 90]
  - lon / longitude / z_m_en_rango_longitudinal [-180, 180]
  - y_m              (elevación relativa o MASL)
  - [columna gravity]
  - unit

RECOMENDADO:
  - elevation_masl
  - uncertainty
  - instrument_id
  - gravity_type     (free_air_anomaly | bouguer_anomaly)
```

#### LEVEL 5 — PROFESSIONAL_SURVEY
```
REQUIRED (CSV):
  - station_id
  - lat              (columna explícita, no inferida de x_m)
  - lon              (columna explícita)
  - elevation_masl   (elevación sobre nivel del mar, no relativa)
  - [columna gravity] = free_air_anomaly | bouguer_anomaly
  - unit
  - uncertainty      (por observación)
  - instrument_id

STRONGLY RECOMMENDED:
  - timestamp
  - quality_flag
  - terrain_correction  (si bouguer_anomaly)
  - free_air_correction (si free_air_anomaly)
  - gravity_type        ("free_air_anomaly" | "bouguer_anomaly")
```

### 5.2 Aliases de columnas que el parser DEBE reconocer (nueva funcionalidad requerida)

Esta es una brecha crítica actual. El parser detecta coordenadas por rangos numéricos pero NO por nombres de columna. La implementación de R3.5 debe agregar un sistema de aliases:

```python
COLUMN_ALIASES = {
    "x_m": ["x_m", "easting", "east", "utm_e", "x", "lon_utm"],
    "z_m": ["z_m", "northing", "north", "utm_n", "z", "lat_utm"],
    "lat": ["lat", "latitude", "latitud", "y_wgs84"],
    "lon": ["lon", "longitude", "longitud", "x_wgs84"],
    "elevation_masl": ["elevation_masl", "elevation", "elev", "alt", "altura_masl", "z_masl", "cota"],
    "gravity_anomaly": ["gravity_anomaly", "g_anomaly", "anomaly", "ba", "faa"],
    "station_id": ["station_id", "id", "station", "punto", "estacion", "name"],
}
```

---

## SECCIÓN 6 — HARD GATES BACKEND

### 6.1 Definición de hard gate

Un **hard gate** es una condición verificada en el backend ANTES de ejecutar el solver. Si falla, retorna HTTP 422 con detalle del bloqueo. No es una advertencia — es un bloqueo.

### 6.2 Lista de hard gates (ordenados por severidad)

#### GATE-1: MINIMUM_OBSERVATIONS (ya existe)
```python
if len(valid_rows) < 10:
    raise SpatialGateError("GATE-1", "Menos de 10 observaciones válidas.")
```
**Estado:** IMPLEMENTADO en `gravity_import_service.py`

#### GATE-2: ZERO_GRAVITY (ya existe)
```python
if all_gravity_zero:
    raise SpatialGateError("GATE-2", "Todos los valores de gravedad son aproximadamente cero.")
```
**Estado:** IMPLEMENTADO en `gravity_import_service.py`

#### GATE-3: NO_SPATIAL_DATA_HARD_BLOCK (nuevo — R3.5)
```python
# Aplica cuando spatial_readiness_level == 0 Y gravity_type != "synthetic_demo"
if spatial.spatial_readiness_level == 0 and not is_synthetic:
    raise SpatialGateError(
        "GATE-3",
        "El CSV no contiene coordenadas geográficas válidas. "
        "Proporcione coordenadas UTM/geográficas o un punto de anclaje. "
        "Solo se permite inversión sin coordenadas para datos sintéticos/demo."
    )
```
**Estado:** NO IMPLEMENTADO — REQUERIDO POR R3.5

#### GATE-4: UTM_ZONE_REQUIRED_FOR_FULL_GEOREF (nuevo — R3.5)
```python
# Aplica cuando coordinate_system == "utm" y utm_zone no declarado
# NO bloquea inversión — degrada a LEVEL 2 y emite warning fuerte
if coord_system == "utm" and utm_zone is None:
    spatial.spatial_readiness_level = 2  # UTM_NO_ZONE
    spatial.can_run_3d_inversion = True  # permite pero con advertencia
    spatial.required_user_acknowledgement = (
        "ADVERTENCIA: Zona UTM no declarada. El modelo puede tener un offset "
        "de hasta ~100 km. Declare la zona UTM para georef precisa."
    )
```
**Estado:** NO IMPLEMENTADO — REQUERIDO POR R3.5

#### GATE-5: FAVORABILITY_SPATIAL_CAP (nuevo — R3.5)
```python
# Aplica en favorability_service.py
MAX_FAVORABILITY_BY_LEVEL = {
    0: 0,     # Bloqueado por GATE-3 antes de llegar aquí
    1: 45,    # Cap en 45/100 — no puede ser HIGH
    2: 60,    # Cap en 60/100 — puede llegar a MEDIUM-HIGH
    3: 85,    # Cap leve para UTM con zona
    4: 100,   # Sin cap — georef completo
    5: 100,   # Sin cap — profesional
}
```
**Estado:** NO IMPLEMENTADO — REQUERIDO POR R3.5

#### GATE-6: PRIORITY_CLASS_SPATIAL_CAP (nuevo — R3.5)
```python
MAX_PRIORITY_BY_LEVEL = {
    0: None,      # No se calcula
    1: "LOW",
    2: "LOW",     # UTM sin zona no puede ser MEDIUM ni HIGH
    3: "HIGH",    # UTM con zona puede ser HIGH
    4: "HIGH",
    5: "HIGH",
}
```
**Estado:** NO IMPLEMENTADO — REQUERIDO POR R3.5

#### GATE-7: REPORT_LANGUAGE_GATE (nuevo — R3.5)
```python
# En report_generator.py — no bloquea el report, degrada el lenguaje
if spatial_level <= 1:
    # Prohibir cualquier mención de ubicación geográfica absoluta
    # Prohibir "el yacimiento se encuentra en..." "ubicado en..."
    # Sustituir por "modelo conceptual en coordenadas relativas"
    use_geographic_language = False
```
**Estado:** NO IMPLEMENTADO — REQUERIDO POR R3.5

### 6.3 Tabla de hard gates por nivel

| Gate | LEVEL 0 | LEVEL 1 | LEVEL 2 | LEVEL 3 | LEVEL 4 | LEVEL 5 |
|------|---------|---------|---------|---------|---------|---------|
| GATE-3 (no spatial) | BLOQUEA | Pass | Pass | Pass | Pass | Pass |
| GATE-4 (utm sin zona) | N/A | N/A | WARN | N/A | N/A | N/A |
| GATE-5 (fav cap) | 0 | ≤45 | ≤60 | ≤85 | 100 | 100 |
| GATE-6 (priority cap) | NONE | LOW | LOW | HIGH | HIGH | HIGH |
| GATE-7 (report lang) | BLOQUEA | BLOQUEA | WARN | Pass | Pass | Pass |

### 6.4 Excepción: modo SYNTHETIC_DEMO

```python
SYNTHETIC_BYPASS_GATES = [3, 4, 5, 6, 7]  # GATE-1 y GATE-2 siempre aplican

def is_synthetic_demo(import_result: GravityImportResult) -> bool:
    return import_result.gravity_type == "synthetic_demo"
```

Los datos `synthetic_demo` bypasean GATE-3 a GATE-7. Esto permite que los demos del sistema funcionen sin coordenadas reales. Aun así, se muestra badge "DEMO SINTÉTICO" prominente.

---

## SECCIÓN 7 — CAMBIOS EN PREVIEW (`/gravity-import/preview`)

### 7.1 Estado actual del endpoint `/preview`

Actualmente calcula `_classify_georef_full(ct_obj, None, None, None)` sin anchor. Retorna georef_confidence pero NO retorna spatial_readiness_level.

### 7.2 Cambios requeridos en `/preview`

**Agregar a la respuesta de preview:**

```python
class PreviewResponse(BaseModel):
    # ... campos existentes ...
    
    # NUEVO R3.5
    spatial_readiness: SpatialReadinessPreview  # ver schema en Sección 6.5

class SpatialReadinessPreview(BaseModel):
    level: int                           # 0–5
    level_name: str                      # "NO_SPATIAL_DATA", etc.
    can_run_3d_inversion: bool
    can_run_conceptual_inversion: bool   # solo LEVEL 1 con anchor
    blocking_reason: Optional[str]       # None si puede invertir
    required_user_input: List[str]       # ["utm_zone", "anchor_lat", ...]
    warnings: List[str]                  # advertencias no-bloqueantes
    upgrade_path: Optional[str]          # "Proporcione UTM zone para LEVEL 3"
```

**Lógica de `compute_spatial_readiness_preview()`:**
- No recibe anchor (el usuario aún no lo declaró en preview)
- Infiere nivel máximo alcanzable con el CSV tal como está
- Indica qué campos adicionales del form activarían un nivel mayor

### 7.3 Información de upgrade path en preview

El preview debe informar al usuario qué puede hacer para mejorar el nivel espacial:

| CSV detectado como | Nivel actual | Upgrade disponible |
|-------------------|-------------|-------------------|
| `local_meters`, sin anchor | LEVEL 0 | "Proporcione lat/lon de anclaje → LEVEL 1" |
| `local_meters`, con anchor | LEVEL 1 | "Reemplace con CSV UTM para LEVEL 3" |
| `utm`, sin zona | LEVEL 2 | "Declare zona UTM → LEVEL 3" |
| `utm`, con zona | LEVEL 3 | "Agregue lat/lon reales → LEVEL 4" |
| `latlon` | LEVEL 4 | "Agregue elevation_masl y uncertainty → LEVEL 5" |

---

## SECCIÓN 8 — CAMBIOS EN INVERT (`/gravity-import/invert`)

### 8.1 Arquitectura de gates en `/invert`

El endpoint `/invert` debe ejecutar los gates en este orden, ANTES de llamar a `run_geophysics_inversion()`:

```python
@router.post("/gravity-import/invert")
async def invert_gravity(
    project_id: str = Form(...),
    file: UploadFile = File(...),
    # campos existentes...
    utm_zone: Optional[str] = Form(None),  # R2 — ya existe
    anchor_lat: Optional[float] = Form(None),  # R3.5 — nuevo
    anchor_lon: Optional[float] = Form(None),  # R3.5 — nuevo
    acknowledge_low_georef: Optional[bool] = Form(False),  # R3.5 — nuevo
    # ...
):
    # 1. Parsear e importar CSV (ya existe)
    import_result = gravity_import_service.import_csv(file, ...)
    
    # 2. Clasificar sistema de coordenadas (ya existe)
    coord_system = csv_analysis_service.detect_coordinate_system(import_result)
    
    # 3. NUEVO R3.5: Calcular SpatialReadiness
    spatial = compute_spatial_readiness(
        coord_system=coord_system,
        utm_zone=utm_zone,
        anchor_lat=anchor_lat,
        anchor_lon=anchor_lon,
        gravity_type=import_result.gravity_type,
    )
    
    # 4. NUEVO R3.5: Aplicar hard gates
    apply_spatial_hard_gates(spatial, acknowledge_low_georef)
    
    # 5. Resto del pipeline (ya existe)
    # ...
    run_geophysics_inversion(...)
```

### 8.2 Función `compute_spatial_readiness()`

```python
def compute_spatial_readiness(
    coord_system: CoordSystemDetection,
    utm_zone: Optional[str],
    anchor_lat: Optional[float],
    anchor_lon: Optional[float],
    gravity_type: str,
) -> SpatialReadiness:
    
    is_synthetic = gravity_type == "synthetic_demo"
    
    if coord_system.system == "latlon":
        level = 4
        level_name = "GEOGRAPHIC_COORDS"
    elif coord_system.system == "utm":
        if utm_zone:
            level = 3
            level_name = "UTM_WITH_ZONE"
        else:
            level = 2
            level_name = "UTM_NO_ZONE"
    elif coord_system.system == "local_meters":
        if anchor_lat is not None and anchor_lon is not None:
            level = 1
            level_name = "LOCAL_WITH_ANCHOR"
        else:
            level = 0
            level_name = "NO_SPATIAL_DATA"
    else:  # unknown
        level = 0
        level_name = "NO_SPATIAL_DATA"
    
    # Professional survey check (LEVEL 5)
    if level == 4 and has_professional_fields(coord_system):
        level = 5
        level_name = "PROFESSIONAL_SURVEY"
    
    return SpatialReadiness(
        spatial_readiness_level=level,
        spatial_readiness_name=level_name,
        can_run_3d_inversion=(level >= 1 or is_synthetic),
        can_run_conceptual_inversion=(level >= 1),
        can_use_dem=(level >= 3),
        can_compute_voxel_masl=(level >= 3),
        max_priority_class_allowed=_get_max_priority(level),
        max_favorability_score=_get_max_favorability(level),
        required_user_acknowledgement=_get_required_ack(level),
        is_synthetic_bypass=is_synthetic,
    )
```

### 8.3 Función `apply_spatial_hard_gates()`

```python
def apply_spatial_hard_gates(
    spatial: SpatialReadiness,
    acknowledge_low_georef: bool,
) -> None:
    """Raises SpatialGateError si el nivel espacial no permite inversión."""
    
    if spatial.is_synthetic_bypass:
        return  # bypass para datos sintéticos
    
    # GATE-3: Bloqueo total LEVEL 0
    if spatial.spatial_readiness_level == 0:
        raise SpatialGateError(
            gate_id="GATE-3",
            level=spatial.spatial_readiness_level,
            message=(
                "El CSV no tiene información espacial suficiente para una inversión 3D. "
                "Proporcione coordenadas UTM o lat/lon, o un punto de anclaje."
            ),
            upgrade_path=(
                "Para continuar: (a) Agregue campo utm_zone si sus coordenadas son UTM, "
                "(b) Proporcione anchor_lat y anchor_lon para modelo conceptual, "
                "(c) Use un CSV con columnas lat/lon."
            ),
        )
    
    # GATE-4: UTM sin zona — no bloquea pero requiere acknowledgement
    if spatial.spatial_readiness_level == 2 and not acknowledge_low_georef:
        raise SpatialGateError(
            gate_id="GATE-4",
            level=2,
            message=(
                "Se detectaron coordenadas UTM pero no se declaró la zona. "
                "El modelo puede tener un offset geográfico de hasta ~100 km."
            ),
            requires_acknowledgement=True,
            upgrade_path="Declare utm_zone en el formulario o envíe acknowledge_low_georef=true para continuar con esta limitación.",
        )
    
    # GATE para LEVEL 1 — siempre requiere acknowledgement (modelo conceptual)
    if spatial.spatial_readiness_level == 1 and not acknowledge_low_georef:
        raise SpatialGateError(
            gate_id="GATE-1C",
            level=1,
            message=(
                "El modelo se posicionará usando un punto de anclaje aproximado. "
                "La georeferencia es de baja confianza — no use para decisiones de sondaje."
            ),
            requires_acknowledgement=True,
        )
```

### 8.4 Nuevo campo `acknowledge_low_georef` en el form

El frontend debe agregar:
- Un checkbox: "Entiendo que este modelo tiene georef limitada y acepto continuar"
- Visible solo cuando spatial_readiness_level ≤ 2
- Enviar como `acknowledge_low_georef=true` en el form

---

## SECCIÓN 9 — CAMBIOS EN FAVORABILITY

### 9.1 El problema

`favorability_service.py` calcula un score 0–100 y una clasificación (BAJO/MEDIO/ALTO) sin considerar el nivel espacial. Un CSV sin coordenadas reales puede producir `favorability = 78 → ALTO`.

Esto es misleading: favorabilidad alta implica recomendación de exploración, que solo tiene sentido si sabemos DÓNDE está el target.

### 9.2 Cambios requeridos en `compute_favorability_score()`

```python
def compute_favorability_score(
    inversion_result: InversionResult,
    project_meta: ProjectMeta,
    spatial_readiness: SpatialReadiness,  # NUEVO parámetro R3.5
) -> FavorabilityResult:
    
    # Calcular score base (lógica existente)
    base_score = _compute_base_score(inversion_result, project_meta)
    
    # NUEVO R3.5: Aplicar cap de spatial readiness
    max_score = MAX_FAVORABILITY_BY_LEVEL[spatial_readiness.spatial_readiness_level]
    capped_score = min(base_score, max_score)
    
    # NUEVO R3.5: Aplicar cap de priority class
    max_priority = spatial_readiness.max_priority_class_allowed
    
    # Recalcular clasificación con score capeado
    classification = _classify_score(capped_score, max_priority)
    
    return FavorabilityResult(
        score=capped_score,
        base_score=base_score,  # Score sin cap (informativo)
        spatial_readiness_cap_applied=(capped_score < base_score),
        spatial_readiness_cap_reason=_get_cap_reason(spatial_readiness),
        classification=classification,
        # ... otros campos existentes
    )
```

### 9.3 Valores de cap por nivel

```python
MAX_FAVORABILITY_BY_LEVEL = {
    0: 0,    # No debe llegar aquí (GATE-3 bloquea antes)
    1: 45,   # CONCEPTUAL — max MEDIO-BAJO
    2: 60,   # UTM sin zona — max MEDIO
    3: 85,   # UTM con zona — puede ser ALTO pero con advertencia
    4: 100,  # Lat/lon completo — sin cap
    5: 100,  # Profesional — sin cap
}
```

### 9.4 Texto de explicación del cap (para el reporte)

```python
CAP_REASON_TEXT = {
    1: (
        "La favorabilidad está limitada a MEDIO porque el modelo usa coordenadas locales "
        "con anclaje aproximado. Para una clasificación completa, proporcione coordenadas UTM o lat/lon."
    ),
    2: (
        "La favorabilidad está limitada a MEDIO porque la zona UTM no fue declarada. "
        "Declare la zona UTM para habilitar clasificación completa."
    ),
    3: (
        "La favorabilidad está levemente limitada porque las coordenadas UTM no fueron "
        "verificadas contra referencia absoluta."
    ),
}
```

---

## SECCIÓN 10 — CAMBIOS EN FRONTEND

### 10.1 Cambios en `GravityCsvPreviewPanel.tsx`

#### 10.1.1 Nuevo badge de spatial readiness

Agregar junto al badge de georef_confidence un badge de spatial readiness:

```typescript
// Nuevo helper
function getSpatialReadinessBadgeLabel(level: number): string {
    const labels: Record<number, string> = {
        0: "SIN COORDENADAS",
        1: "LOCAL + ANCLAJE",
        2: "UTM SIN ZONA",
        3: "UTM CON ZONA",
        4: "GEOREF COMPLETO",
        5: "LEVANTAMIENTO PROF.",
    };
    return labels[level] ?? "DESCONOCIDO";
}

function getSpatialReadinessBadgeClass(level: number): string {
    if (level <= 0) return "badge-red";
    if (level <= 2) return "badge-yellow";
    if (level === 3) return "badge-blue";
    return "badge-green";
}
```

#### 10.1.2 Bloqueo del botón "Invertir"

```typescript
// En el handler del botón de inversión
const canRunInversion = spatialReadiness?.can_run_3d_inversion ?? false;
const requiresAck = spatialReadiness?.spatial_readiness_level <= 2;
const hasAcknowledged = formState.acknowledge_low_georef;

const invertButtonDisabled = !canRunInversion || (requiresAck && !hasAcknowledged);
```

#### 10.1.3 Checkbox de acknowledgement

```typescript
{spatialReadiness && spatialReadiness.spatial_readiness_level <= 2 && (
    <div className="spatial-ack-box warning-border">
        <p className="warning-text">
            {spatialReadiness.required_user_acknowledgement}
        </p>
        <label>
            <input
                type="checkbox"
                checked={formState.acknowledge_low_georef}
                onChange={(e) => setFormState(prev => ({
                    ...prev,
                    acknowledge_low_georef: e.target.checked
                }))}
            />
            Entiendo las limitaciones y deseo continuar con un modelo de baja georeferencia.
        </label>
    </div>
)}
```

#### 10.1.4 Panel de upgrade path

```typescript
{spatialReadiness?.upgrade_path && (
    <div className="upgrade-path-panel info-border">
        <p className="info-icon">ℹ️ Para mejorar la georeferencia:</p>
        <p>{spatialReadiness.upgrade_path}</p>
    </div>
)}
```

### 10.2 Cambios en `Exploration3DView.tsx`

#### 10.2.1 Banner de modelo conceptual

Cuando `spatialReadiness.level <= 1`:

```typescript
{project.spatial_readiness_level <= 1 && (
    <div className="conceptual-model-banner">
        <span className="banner-icon">⚠</span>
        <span>MODELO CONCEPTUAL — Sin georeferencia real. No usar para sondaje.</span>
    </div>
)}
```

#### 10.2.2 Desactivar capas geoespaciales para niveles bajos

Cuando `level <= 1`, desactivar o grayout:
- Capa de footprint geográfico
- Overlays de DEM
- Coordenadas absolutas en el HUD

### 10.3 Cambios en `useAppStore.ts`

```typescript
// Agregar a GeoReportInfo o crear interfaz SpatialReadinessState
interface SpatialReadinessState {
    spatial_readiness_level: number;        // 0–5
    spatial_readiness_name: string;
    can_run_3d_inversion: boolean;
    can_use_dem: boolean;
    can_compute_voxel_masl: boolean;
    max_priority_class_allowed: string | null;
    max_favorability_score: number;
    required_user_acknowledgement: string | null;
    is_synthetic_bypass: boolean;
}
```

### 10.4 Cambios en `frontendApi.ts`

```typescript
// Agregar tipos
export interface SpatialReadiness {
    spatial_readiness_level: number;
    spatial_readiness_name: string;
    can_run_3d_inversion: boolean;
    can_run_conceptual_inversion: boolean;
    can_use_dem: boolean;
    can_compute_voxel_masl: boolean;
    max_priority_class_allowed: string | null;
    max_favorability_score: number;
    required_user_acknowledgement: string | null;
    upgrade_path: string | null;
    is_synthetic_bypass: boolean;
}

// Agregar al tipo de respuesta de preview
export interface PreviewResponse {
    // ... campos existentes ...
    spatial_readiness: SpatialReadiness;  // NUEVO R3.5
}

// Agregar campo al form de inversión
export interface InvertFormData {
    // ... campos existentes ...
    anchor_lat?: number;          // NUEVO R3.5
    anchor_lon?: number;          // NUEVO R3.5
    acknowledge_low_georef?: boolean;  // NUEVO R3.5
}
```

### 10.5 Texto UI requerido por nivel (copy oficial)

| Nivel | Título del panel | Texto de aviso |
|-------|-----------------|----------------|
| 0 | "CSV sin datos espaciales" | "Este archivo no contiene coordenadas geográficas. Agregue un punto de anclaje o use un CSV con coordenadas UTM/lat-lon para habilitar la inversión." |
| 1 | "Modelo conceptual con anclaje" | "El modelo se posicionará usando el punto de anclaje que declaró. La georeferencia es aproximada. No use los resultados para planificación de sondaje sin verificación de campo." |
| 2 | "UTM detectado — zona no declarada" | "Se detectaron coordenadas UTM pero la zona no fue especificada. El modelo puede tener un desplazamiento geográfico de hasta 100 km. Declare la zona UTM para corregir esto." |
| 3 | "UTM con zona declarada" | "La georeferencia se realizará con la zona UTM indicada. Si esta zona es incorrecta, el modelo tendrá un desplazamiento geográfico significativo." |
| 4+ | — | No requiere aviso especial |

---

## SECCIÓN 11 — CAMBIOS EN REPORTES

### 11.1 Sección de alerta espacial en el reporte HTML

El `report_generator.py` debe generar una sección prominente cuando `spatial_readiness_level <= 2`:

```html
<!-- SECCIÓN NUEVA R3.5: Solo cuando level <= 2 -->
<div class="spatial-readiness-alert">
    <h2>⚠ LIMITACIÓN DE GEOREFERENCIA — IMPORTANTE</h2>
    <p>
        Este modelo fue generado con datos de nivel espacial <strong>{level_name}</strong>
        ({level}/5). Las siguientes capacidades están limitadas:
    </p>
    <ul>
        <li>❌ Las coordenadas absolutas del modelo NO son confiables</li>
        <li>❌ No utilizar para planificación directa de sondajes</li>
        <li>❌ No citar coordenadas de este reporte en documentos técnicos externos</li>
        {#if level == 0 or level == 1}
        <li>❌ Este es un modelo conceptual — no representa una ubicación geológica verificada</li>
        {/if}
    </ul>
    <p><strong>Para habilitar un modelo georreferenciado completo:</strong> {upgrade_path}</p>
</div>
```

### 11.2 Modificar lenguaje del reporte según nivel

**Cuando `level <= 1`:** Buscar y reemplazar frases que impliquen ubicación absoluta:

| Frase prohibida | Frase alternativa |
|----------------|------------------|
| "El cuerpo mineralizado se ubica en..." | "En el modelo conceptual, el cuerpo mineralizado se detecta en posición relativa..." |
| "Coordenadas del centroide: lat X, lon Y" | "Posición relativa en el modelo: x_m, z_m (sin georef real)" |
| "La anomalía se encuentra a N km de..." | "La anomalía se detecta a N km del origen del modelo local" |
| "Se recomienda sondaje en lat X, lon Y" | "Se recomienda verificar coordenadas antes de planificar sondaje" |

**Implementación:** Filtro de texto en `report_generator.py` o template condicional por nivel.

### 11.3 Sección de spatial readiness en el reporte

Agregar tabla de spatial readiness junto a la tabla de georef actual:

```python
def _spatial_readiness_section_html(spatial: SpatialReadiness) -> str:
    level_colors = {0: "red", 1: "orange", 2: "yellow", 3: "blue", 4: "green", 5: "green"}
    color = level_colors.get(spatial.spatial_readiness_level, "gray")
    
    return f"""
    <div class="report-section">
        <h3>Suficiencia Espacial del Modelo</h3>
        <table>
            <tr><td>Nivel</td><td class="badge-{color}">{spatial.spatial_readiness_level} — {spatial.spatial_readiness_name}</td></tr>
            <tr><td>Inversión 3D habilitada</td><td>{'✓ Sí' if spatial.can_run_3d_inversion else '✗ No'}</td></tr>
            <tr><td>DEM co-registrado</td><td>{'✓ Sí' if spatial.can_use_dem else '✗ No'}</td></tr>
            <tr><td>Elevación MASL</td><td>{'✓ Sí' if spatial.can_compute_voxel_masl else '✗ No'}</td></tr>
            <tr><td>Priority class máxima</td><td>{spatial.max_priority_class_allowed or 'N/A'}</td></tr>
            <tr><td>Cap de favorabilidad</td><td>{spatial.max_favorability_score}/100</td></tr>
        </table>
        {f'<p class="warning">{spatial.required_user_acknowledgement}</p>' if spatial.required_user_acknowledgement else ''}
    </div>
    """
```

---

## SECCIÓN 12 — TESTS REQUERIDOS

### 12.1 Test Scenario T1: CSV solo gravedad sin coordenadas (LEVEL 0)

```python
# tests/test_spatial_readiness.py::test_t1_no_spatial_data
CSV_T1 = """
station_id,x_m,y_m,z_m,gravity_anomaly,unit
P001,1,0,1,-45.1,mGal
P002,2,0,2,-44.8,mGal
...  # 10+ filas
"""
# utm_zone=None, anchor_lat=None, anchor_lon=None
# Expected:
assert spatial.spatial_readiness_level == 0
assert spatial.can_run_3d_inversion == False
assert response.status_code == 422
assert "GATE-3" in response.json()["detail"]
```

### 12.2 Test Scenario T2: CSV local con anchor (LEVEL 1)

```python
# tests/test_spatial_readiness.py::test_t2_local_with_anchor
# anchor_lat=-28.34, anchor_lon=-70.54
# Expected:
assert spatial.spatial_readiness_level == 1
assert spatial.can_run_3d_inversion == True
assert spatial.max_priority_class_allowed == "LOW"
assert response.status_code == 422  # requiere acknowledge
# Con acknowledge_low_georef=True:
assert response_ack.status_code == 200
assert result.favorability_score <= 45
```

### 12.3 Test Scenario T3: UTM sin zona (LEVEL 2)

```python
# x_m en rango 357000–360000 (UTM easting válido)
# z_m en rango 6870000–6875000 (UTM northing válido)
# utm_zone=None
# Expected:
assert spatial.spatial_readiness_level == 2
assert spatial.can_run_3d_inversion == True  # permite pero con ack
assert response.status_code == 422  # requiere acknowledge (GATE-4)
assert "GATE-4" in response.json()["detail"]
assert "utm_zone" in response.json()["upgrade_path"]
```

### 12.4 Test Scenario T4: UTM con zona declarada (LEVEL 3)

```python
# utm_zone="19S"
# Expected:
assert spatial.spatial_readiness_level == 3
assert spatial.can_run_3d_inversion == True
assert spatial.max_priority_class_allowed == "HIGH"
assert spatial.can_use_dem == True
assert response.status_code == 200
assert result.favorability_score <= 85
```

### 12.5 Test Scenario T5: Lat/lon completo (LEVEL 4)

```python
# x_m en [-180,180], z_m en [-90,90]
# Expected:
assert spatial.spatial_readiness_level == 4
assert spatial.can_run_3d_inversion == True
assert spatial.max_favorability_score == 100
assert spatial.can_use_dem == True
assert response.status_code == 200
```

### 12.6 Test Scenario T6: Levantamiento profesional (LEVEL 5)

```python
# lat/lon explícitas + elevation_masl + uncertainty + instrument_id
# gravity_type = "free_air_anomaly"
# Expected:
assert spatial.spatial_readiness_level == 5
assert spatial.can_compute_voxel_masl == True
assert result.dem_coresistered == True  # si DEM disponible
```

### 12.7 Test Scenario T7: Datos sintéticos con LEVEL 0 (bypass)

```python
# gravity_type="synthetic_demo", sin coordenadas reales
# Expected:
assert spatial.is_synthetic_bypass == True
assert spatial.can_run_3d_inversion == True  # bypass
assert response.status_code == 200
# Pero:
assert result.priority_class != "HIGH"  # No cap bypass — la demo puede mostrar HIGH
```

### 12.8 Test Scenario T8: UTM con zona incorrecta

```python
# utm_zone="99X" (zona inválida)
# Expected:
# Validación de formato de zona UTM
assert response.status_code == 422
assert "utm_zone" in response.json()["detail"]
assert "formato inválido" in response.json()["detail"]
```

### 12.9 Test Scenario T9: Cap de favorabilidad verificado

```python
# LEVEL 1, anchor provisto, acknowledge=True
# Simular inversion_result con base_score = 90
# Expected:
assert result.favorability_score <= 45
assert result.spatial_readiness_cap_applied == True
assert "45" in result.spatial_readiness_cap_reason
```

### 12.10 Test Scenario T10: Reporte con lenguaje degradado (LEVEL 0–1)

```python
# LEVEL 1 o LEVEL 0 (sintético)
# Expected HTML:
assert "MODELO CONCEPTUAL" in report_html
assert "No utilizar para planificación directa de sondajes" in report_html
# Verificar ausencia de lenguaje de ubicación absoluta:
assert "coordenadas del centroide" not in report_html.lower()
assert "se ubica en lat" not in report_html.lower()
```

---

## SECCIÓN 13 — QA MANUAL

### 13.1 Checklist QA por flujo

#### Flujo A: CSV sin coordenadas
- [ ] Upload CSV tipo E (local sin georef)
- [ ] Preview muestra badge ROJO "SIN COORDENADAS"
- [ ] Panel de upgrade path visible con instrucciones
- [ ] Botón "Invertir" bloqueado (disabled)
- [ ] Sin checkbox de acknowledgement visible
- [ ] Error 422 con GATE-3 si se intenta por API directa

#### Flujo B: CSV local con anchor (LEVEL 1)
- [ ] Upload CSV tipo D (local)
- [ ] Badge AMARILLO "LOCAL + ANCLAJE"
- [ ] Campos anchor_lat/anchor_lon visibles en el form
- [ ] Al llenar anchor, checkbox de acknowledgement aparece
- [ ] Botón bloqueado hasta que checkbox esté marcado
- [ ] Inversión exitosa con advertencia visible
- [ ] Favorability ≤ 45
- [ ] Priority_class = LOW o MEDIUM (no HIGH)
- [ ] Banner "MODELO CONCEPTUAL" visible en 3D view

#### Flujo C: CSV UTM sin zona (LEVEL 2)
- [ ] Badge AMARILLO "UTM SIN ZONA"
- [ ] Mensaje de advertencia de offset de 100km visible
- [ ] Campo utm_zone visible y solicitado
- [ ] Upgrade path: "Declare zona UTM → LEVEL 3"
- [ ] Sin zona + acknowledge: inversión con cap de favorability ≤ 60
- [ ] Con zona declarada: nivel sube a LEVEL 3 automáticamente

#### Flujo D: CSV UTM con zona (LEVEL 3)
- [ ] Badge AZUL "UTM CON ZONA"
- [ ] Sin checkbox de ack requerido
- [ ] Inversión exitosa, favorability sin cap duro (máx 85)
- [ ] DEM disponible en 3D view

#### Flujo E: CSV lat/lon (LEVEL 4)
- [ ] Badge VERDE "GEOREF COMPLETO"
- [ ] Inversión directa sin obstáculos
- [ ] Favorability sin cap
- [ ] Priority_class puede ser HIGH

#### Flujo F: Sintéticos (LEVEL 0 bypass)
- [ ] gravity_type = "synthetic_demo"
- [ ] Badge especial "DEMO SINTÉTICO"
- [ ] Inversión sin bloqueo
- [ ] Advertencias de demo visibles pero no bloqueantes

### 13.2 Checklist QA de regresión (no tocar features existentes)

- [ ] CSVs existentes que pasaban antes siguen pasando (no rompemos nada)
- [ ] R1 footprint badges siguen funcionando
- [ ] R2 UTM zone field sigue funcionando
- [ ] R3 DEM elevation sigue funcionando cuando aplica
- [ ] Report HTML genera sin errores para todos los niveles

---

## SECCIÓN 14 — RIESGOS

### 14.1 Riesgos de implementación

| Riesgo | Severidad | Probabilidad | Mitigación |
|--------|-----------|-------------|-----------|
| GATE-3 rompe flujos de demo existentes | ALTA | MEDIA | Asegurar bypass para synthetic_demo antes de mergear |
| Cap de favorabilidad sorprende usuarios con datos reales | MEDIA | BAJA | Mostrar score base + score capeado en UI |
| Alias de columnas (`lat`, `lon`) introduce regresiones en parser | MEDIA | MEDIA | Tests exhaustivos antes de cambiar parser |
| Frontend bloquea botón y usuarios no entienden por qué | MEDIA | MEDIA | Mensajes claros + upgrade path visible |
| `acknowledge_low_georef` no se envía en todos los clientes API | ALTA | ALTA | Default a False en backend, error claro |

### 14.2 Riesgos de producción

| Riesgo | Severidad | Mitigación |
|--------|-----------|-----------|
| Proyectos guardados con georef=MISSING sin nivel spatial_readiness | MEDIA | Migration: asignar LEVEL 0 retrospectivamente para proyectos sin spatial_readiness |
| Favorability histórica no recalculada | BAJA | No recalcular retroactivamente; solo aplica a nuevos runs |
| Reportes existentes sin sección de spatial readiness | BAJA | No regenerar; nota en CHANGELOG |

### 14.3 Riesgo científico (el más importante)

> **Si GATE-3 no se implementa y un usuario presenta un reporte de TerraQuantum a una empresa minera con datos de LEVEL 0, el sistema puede haber producido una recomendación de exploración sin ninguna base geoespacial real. Esto no es solo un bug de UX — es un riesgo de credibilidad científica del producto.**

---

## SECCIÓN 15 — PLAN DE EJECUCIÓN POR SUBFASES

### Fase R3.5-A: Schema y clasificación (bajo riesgo — ~2h)

**Archivos a tocar:**
- `terraquantum-backend/schemas/gravity_import_schema.py` — agregar `SpatialReadiness` Pydantic schema
- `terraquantum-backend/schemas/project_schema.py` — agregar campo `spatial_readiness` a `ProjectMeta`

**Qué hace:** Define el schema, sin lógica. Sin riesgo de regresión.

**Test:** Importar schema sin error.

---

### Fase R3.5-B: Servicio de clasificación (riesgo medio — ~3h)

**Archivos a tocar:**
- `terraquantum-backend/services/spatial_readiness_service.py` ← NUEVO servicio
  - `compute_spatial_readiness(coord_system, utm_zone, anchor_lat, anchor_lon, gravity_type) → SpatialReadiness`
  - `apply_spatial_hard_gates(spatial, acknowledge) → None`

**Qué NO tocar:** Servicios existentes hasta que el nuevo servicio esté testeado.

**Test:** T1–T8 del Sección 12.

---

### Fase R3.5-C: Hard gates en `/invert` (riesgo medio-alto — ~2h)

**Archivos a tocar:**
- `terraquantum-backend/api/gravity_import_api.py` — insertar llamada a `apply_spatial_hard_gates()` ANTES de `run_geophysics_inversion()`

**Precaución:** Este es el archivo más crítico del backend. Validar que:
- Los datos sintéticos bypasean correctamente
- Los CSVs LEVEL 3–5 existentes siguen pasando
- El error 422 retorna estructura JSON útil para el frontend

**Test:** T1–T6 del Sección 12, más tests de regresión de rutas existentes.

---

### Fase R3.5-D: Cap de favorabilidad (riesgo medio — ~2h)

**Archivos a tocar:**
- `terraquantum-backend/services/favorability_service.py` — agregar parámetro `spatial_readiness` y aplicar cap

**Precaución:** No cambiar la lógica de cálculo base. Solo añadir cap al final.

**Test:** T9 del Sección 12. Verificar que favorability = 100 sigue posible para LEVEL 4–5.

---

### Fase R3.5-E: Preview endpoint (riesgo bajo — ~1h)

**Archivos a tocar:**
- `terraquantum-backend/api/gravity_import_api.py` — agregar `spatial_readiness_preview` a la respuesta de `/preview`

**Test:** Llamar /preview con varios tipos de CSV y verificar `spatial_readiness` en respuesta.

---

### Fase R3.5-F: Frontend — tipos y store (riesgo bajo — ~1h)

**Archivos a tocar:**
- `terraquantum-web/lib/terraquantum/frontendApi.ts` — agregar tipos `SpatialReadiness`, `InvertFormData` actualizado
- `terraquantum-web/store/useAppStore.ts` — agregar `SpatialReadinessState` a interfaces

**Test:** TypeScript compile sin errores.

---

### Fase R3.5-G: Frontend — UI/UX (riesgo medio — ~4h)

**Archivos a tocar:**
- `terraquantum-web/componentes/GravityCsvPreviewPanel.tsx` — badges, checkbox, upgrade path
- `terraquantum-web/componentes/views/Exploration3DView.tsx` — banner conceptual
- `terraquantum-web/componentes/huds/GeoDashboard.tsx` — indicador de nivel espacial

**Test:** QA manual Flujos A–F del Sección 13.

---

### Fase R3.5-H: Reportes (riesgo bajo — ~2h)

**Archivos a tocar:**
- `terraquantum-backend/reporting/report_generator.py` — sección de spatial readiness, filtro de lenguaje geográfico

**Test:** T10 del Sección 12. Generar reportes para cada nivel y revisar contenido.

---

### Fase R3.5-I: Column aliases en parser (riesgo medio — ~3h)

**Archivos a tocar:**
- `terraquantum-backend/services/gravity_import_service.py` — agregar `COLUMN_ALIASES` y lógica de mapping

**Precaución:** Alto riesgo de regresión si se tocan columnas requeridas. Solo agregar aliases OPCIONALES. Los aliases de `lat`/`lon` solo deben activarse si las columnas `x_m`/`z_m` NO están presentes.

**Test:** T5 con CSV tipo A (lat/lon explícitas). Verificar que CSVs existentes con `x_m`/`z_m` siguen funcionando.

---

### Orden de ejecución recomendado

```
R3.5-A (schema) 
    → R3.5-B (servicio, tests)
    → R3.5-C (hard gates, tests regresión)
    → R3.5-D (favorability cap)
    → R3.5-E (preview)
    → R3.5-F (FE tipos)
    → R3.5-G (FE UI)
    → R3.5-H (reportes)
    → R3.5-I (column aliases — ÚLTIMA porque más riesgosa)
```

Cada fase puede ser un commit separado y un PR independiente. No mezclar fases.

---

## SECCIÓN 16 — PROMPTS DE IMPLEMENTACIÓN SUGERIDOS

### Prompt R3.5-A (Schema)

```
Implementa Fase R3.5-A del contrato R3.5 en TerraQuantum.

SOLO tocar:
- terraquantum-backend/schemas/gravity_import_schema.py
- terraquantum-backend/schemas/project_schema.py

Agregar el schema Pydantic SpatialReadiness con estos campos:
  - spatial_readiness_level: int (0–5)
  - spatial_readiness_name: str
  - can_run_3d_inversion: bool
  - can_run_conceptual_inversion: bool
  - can_use_dem: bool
  - can_compute_voxel_masl: bool
  - max_priority_class_allowed: Optional[str]
  - max_favorability_score: int (0–100)
  - required_user_acknowledgement: Optional[str]
  - upgrade_path: Optional[str]
  - is_synthetic_bypass: bool

En project_schema.py, agregar campo opcional spatial_readiness: Optional[SpatialReadiness] = None a ProjectMeta.

NO tocar servicios, APIs ni frontend.
Referencia: docs/TERRAQUANTUM_INDUSTRIAL_INPUT_CONTRACT_SPEC.md Sección 8.2
```

---

### Prompt R3.5-B (Servicio de clasificación)

```
Implementa Fase R3.5-B del contrato R3.5 en TerraQuantum.

SOLO crear:
- terraquantum-backend/services/spatial_readiness_service.py (NUEVO)

NO tocar archivos existentes.

El servicio debe implementar:
1. compute_spatial_readiness(coord_system, utm_zone, anchor_lat, anchor_lon, gravity_type) → SpatialReadiness
2. apply_spatial_hard_gates(spatial, acknowledge_low_georef) → None (raises SpatialGateError)
3. SpatialGateError: excepción con campos gate_id, level, message, upgrade_path, requires_acknowledgement

Lógica completa en docs/TERRAQUANTUM_INDUSTRIAL_INPUT_CONTRACT_SPEC.md Secciones 8.2 y 8.3.
Constantes MAX_FAVORABILITY_BY_LEVEL y MAX_PRIORITY_BY_LEVEL definidas en Secciones 9.3 y 6.2.

Tests: implementar tests/test_spatial_readiness.py con T1–T8 de Sección 12.
```

---

### Prompt R3.5-C (Hard gates en /invert)

```
Implementa Fase R3.5-C del contrato R3.5 en TerraQuantum.

SOLO tocar:
- terraquantum-backend/api/gravity_import_api.py

Prerequisito: spatial_readiness_service.py ya implementado (R3.5-B).

Cambios:
1. Agregar parámetros al endpoint /invert: anchor_lat, anchor_lon, acknowledge_low_georef
2. Después de calcular import_result y coord_system, llamar:
   spatial = compute_spatial_readiness(coord_system, utm_zone, anchor_lat, anchor_lon, import_result.gravity_type)
   apply_spatial_hard_gates(spatial, acknowledge_low_georef)
3. Pasar spatial a run_geophysics_inversion() como parámetro nuevo (si es necesario para el cap)

Ubicación: insertar ANTES de la línea que llama run_geophysics_inversion().

SpatialGateError debe resultar en HTTP 422 con body:
{
    "gate_id": "...",
    "level": N,
    "message": "...",
    "upgrade_path": "...",
    "requires_acknowledgement": bool
}

Referencia: docs/TERRAQUANTUM_INDUSTRIAL_INPUT_CONTRACT_SPEC.md Sección 8.
```

---

### Prompt R3.5-D (Cap favorabilidad)

```
Implementa Fase R3.5-D del contrato R3.5 en TerraQuantum.

SOLO tocar:
- terraquantum-backend/services/favorability_service.py

Prerequisito: SpatialReadiness schema disponible (R3.5-A).

Cambios en compute_favorability_score():
1. Agregar parámetro: spatial_readiness: Optional[SpatialReadiness] = None
2. Calcular base_score con lógica existente (SIN CAMBIAR)
3. Aplicar cap: capped_score = min(base_score, MAX_FAVORABILITY_BY_LEVEL[level])
4. Aplicar cap de priority: max_priority = MAX_PRIORITY_BY_LEVEL[level]
5. Agregar a FavorabilityResult: base_score, spatial_readiness_cap_applied, spatial_readiness_cap_reason

Si spatial_readiness es None: comportamiento exactamente igual al actual (sin cap).

Constantes MAX_FAVORABILITY_BY_LEVEL: {0:0, 1:45, 2:60, 3:85, 4:100, 5:100}
Referencia: docs/TERRAQUANTUM_INDUSTRIAL_INPUT_CONTRACT_SPEC.md Sección 9.
```

---

## APÉNDICE A — SCHEMA PYDANTIC COMPLETO `SpatialReadiness`

```python
from pydantic import BaseModel
from typing import Optional, List
from enum import IntEnum

class SpatialReadinessLevel(IntEnum):
    NO_SPATIAL_DATA = 0
    LOCAL_WITH_ANCHOR = 1
    UTM_NO_ZONE = 2
    UTM_WITH_ZONE = 3
    GEOGRAPHIC_COORDS = 4
    PROFESSIONAL_SURVEY = 5

LEVEL_NAMES = {
    0: "NO_SPATIAL_DATA",
    1: "LOCAL_WITH_ANCHOR",
    2: "UTM_NO_ZONE",
    3: "UTM_WITH_ZONE",
    4: "GEOGRAPHIC_COORDS",
    5: "PROFESSIONAL_SURVEY",
}

MAX_FAVORABILITY_BY_LEVEL = {0: 0, 1: 45, 2: 60, 3: 85, 4: 100, 5: 100}

MAX_PRIORITY_BY_LEVEL = {
    0: None,
    1: "LOW",
    2: "LOW",
    3: "HIGH",
    4: "HIGH",
    5: "HIGH",
}

class SpatialReadiness(BaseModel):
    spatial_readiness_level: int
    spatial_readiness_name: str
    can_run_3d_inversion: bool
    can_run_conceptual_inversion: bool
    can_use_dem: bool
    can_compute_voxel_masl: bool
    max_priority_class_allowed: Optional[str] = None
    max_favorability_score: int
    required_user_acknowledgement: Optional[str] = None
    upgrade_path: Optional[str] = None
    warnings: List[str] = []
    is_synthetic_bypass: bool = False

    class Config:
        use_enum_values = True
```

---

## APÉNDICE B — ESTADO ACTUAL VS. POST-R3.5

| Capacidad | Estado actual | Post-R3.5 |
|-----------|--------------|-----------|
| Bloqueo LEVEL 0 antes de inversión | ✗ NO | ✓ SÍ (GATE-3) |
| Clasificación LEVEL 0–5 | ✗ NO | ✓ SÍ |
| Cap de favorabilidad por nivel | ✗ NO | ✓ SÍ |
| Cap de priority_class por nivel | ✗ NO | ✓ SÍ |
| Badge de spatial readiness en UI | ✗ NO | ✓ SÍ |
| Checkbox de acknowledgement | ✗ NO | ✓ SÍ |
| Upgrade path en UI | ✗ NO | ✓ SÍ |
| Banner "MODELO CONCEPTUAL" en 3D view | ✗ NO | ✓ SÍ |
| Lenguaje degradado en reportes (LEVEL ≤1) | ✗ NO | ✓ SÍ |
| Sección spatial readiness en report HTML | ✗ NO | ✓ SÍ |
| Column aliases (lat, lon, easting...) | ✗ NO | ✓ SÍ (R3.5-I) |
| Bypass para datos sintéticos | ✗ Implícito | ✓ SÍ (explícito) |
| Anchor lat/lon para LEVEL 1 | ✗ NO | ✓ SÍ |
| UTM zone gate (LEVEL 2→3) | Parcial | ✓ SÍ (explícito) |

---

*Documento generado en sesión de auditoría R3.5. Cero líneas de código productivo modificadas.*  
*Referencia de auditoría: gravity_import_api.py, gravity_import_service.py, csv_analysis_service.py,*  
*coordinate_transform_service.py, grid_calculator_service.py, favorability_service.py,*  
*report_generator.py, GravityCsvPreviewPanel.tsx, useAppStore.ts, frontendApi.ts*
