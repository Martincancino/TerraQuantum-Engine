# De CSVs de campo a modelo 3D en TerraQuantum

Guía del flujo completo de datos de campo reales:

```
CSV del gravímetro (sin corregir)
  → POST /v2/gravity-import/invert-with-corrections
  → correcciones automáticas GRS80 + Free-Air + Bouguer + Terreno
  → sigma = piso de ruido del gravímetro (no sobreestimado)
  → inversión 3D con depth weighting formal (W_z, Li & Oldenburg 1998)
  → Observed vs Calculated (parquet + r²)
  → export UBC-GIF (.msh + .den, compatible SimPEG)
  → inversion_report.json con limitaciones honestas
```

---

## 1. Formato del CSV

Columnas mínimas para el flujo completo (datos crudos):

| Columna | Obligatoria | Descripción |
|---|---|---|
| `lat` | sí | Latitud WGS84 en grados decimales |
| `lon` | sí | Longitud WGS84 en grados decimales |
| `elev_m` | sí* | Elevación ortométrica de la estación (m s.n.m.) |
| `g_raw` | sí | Gravedad observada (absoluta) |
| `unit` | sí | `mGal`, `m/s2` o `uGal` (una sola unidad por archivo) |
| `gravity_type` | recomendada | `g_raw` o `absolute_gravity` para datos crudos |

\* Sin `elev_m` solo se aplica la corrección de latitud (GRS80); FAC/BC/TC
quedan omitidas con warning explícito.

Columnas profesionales opcionales: `station_id`, `uncertainty`, `timestamp`,
`instrument_id`, `quality_flag`.

**Datos ya corregidos**: si el CSV trae `gravity_type` =
`bouguer_anomaly`, `complete_bouguer_anomaly` o `free_air_anomaly`, el flujo
NO re-aplica correcciones y usa los valores tal cual.

Rango físico aceptado para gravedad absoluta: 970 000 – 990 000 mGal
(superficie terrestre). Fuera de ese rango el import rechaza el archivo
(probable error de unidades).

---

## 2. Gravímetros soportados y piso de ruido

El parámetro `gravimeter_type` fija el piso de ruido instrumental usado para
ponderar los datos:

```
sigma_i = max(noise_floor, noise_pct · |d_i|)
```

| `gravimeter_type` | noise_floor [mGal] | Instrumento |
|---|---|---|
| `scintrex_cg6` | 0.005 | Scintrex CG-6 (repetibilidad de campo) |
| `zls_burris` | 0.002 | ZLS Burris |
| `lacoste_romberg` | 0.010 | LaCoste & Romberg G/D |
| `unknown` | 0.020 | Conservador (default) |

Por qué importa: el sigma adaptivo heredado (2 % de |d|) sobreestimaba el
ruido ~50× para anomalías de Bouguer (~10 mGal medidos con precisión de
0.005 mGal), colapsando chi²_red a ~0.000 e impidiendo interpretar el ajuste.
Con el piso instrumental, **chi²_red ≈ 1 significa "ajustado al nivel del
ruido real"** (criterio de Morozov).

`noise_pct` (default 0.0) agrega un término relativo para datos con errores
proporcionales a la señal (p. ej. correcciones de terreno inciertas):
valores típicos 0.005–0.02.

---

## 3. Densidad de reducción (`reduction_density`)

| Valor | Cuándo usarlo |
|---|---|
| **2.67 g/cm³** | Default internacional (corteza continental promedio). Úselo si no hay información local. |
| **2.70 g/cm³** | Terrenos carbonatados/metamórficos (calizas, mármoles). |
| **Custom** | Si hay muestras de roca local o un análisis de Nettleton. El backend expone `nettleton_analysis` (densidad que minimiza la correlación anomalía–topografía). |

Regla práctica: en terreno volcánico joven (Andes Centrales) densidades de
2.3–2.5 pueden ser más apropiadas; en cratones, 2.67–2.75.

---

## 4. Ejemplo: CG-6 en Atacama (3000 m de elevación)

CSV `survey_atacama.csv`:

```csv
lat,lon,elev_m,g_raw,unit,gravity_type
-27.101234,-69.301234,3012.45,978632.114,mGal,g_raw
-27.102456,-69.302456,3018.20,978630.887,mGal,g_raw
...
```

Llamada (curl):

```bash
curl -X POST http://localhost:8010/v2/gravity-import/invert-with-corrections \
  -F "file=@survey_atacama.csv" \
  -F "project_id=atacama_2026" \
  -F "gravimeter_type=scintrex_cg6" \
  -F "reduction_density=2.67" \
  -F "apply_terrain=true" \
  -F "dem_type=COP30" \
  -F "terrain_radius=22000"
```

Notas:
- `apply_terrain=true` descarga el DEM Copernicus 30 m vía OpenTopography
  (requiere `OPENTOPO_API_KEY` en el entorno). Si la descarga falla, el flujo
  continúa con Bouguer simple (FAC+BC) y lo declara en `warnings`.
- Sin parámetros de grilla (`nx, ny, nz, block_size, depth`), el backend
  calcula una grilla automática a partir de la extensión y el espaciamiento
  del survey. Puede sobreescribirlos (máx. 80 por dimensión).
- `lambda_mag` default 3.0 (operating point validado). Para surveys locales
  de alta calidad (SNR alto), valores 0.05–0.5 ajustan al nivel del ruido;
  verifique con chi²_red.
- Artefactos por corrida en `data/projects/{pid}/runs/{rid}/`:
  `gravity_corrected.csv`, `block_model.parquet`, `obs_vs_calc.parquet`,
  `model.msh`, `model.den`, `inversion_report.json`.

---

## 5. Interpretación de resultados

### chi²_red (`chi_squared_reduced`)
- **≈ 1.0 (0.5–2.0)**: el modelo ajusta los datos al nivel del ruido del
  instrumento. Es el objetivo.
- **≫ 2**: under-fitting — lambda demasiado alto, ruido real mayor al piso
  declarado, o señal que el modelo no puede reproducir (revisar correcciones,
  regional no removido, bounds de densidad).
- **≪ 0.5**: over-fitting — lambda demasiado bajo (se está ajustando el
  ruido) o piso de ruido declarado mayor que el real.

### RMSE / NRMSE
RMSE en m/s² (1 mGal = 1e-5 m/s²). NRMSE = RMSE / |señal máx|: <5 % se
clasifica GOOD en el reporte.

### r² Observed vs Calculated
Correlación espacial entre anomalía medida y predicha (parquet
`obs_vs_calc.parquet`, panel Obs vs Calc del frontend). > 0.95 esperable en
surveys locales bien corregidos.

### DOI (Depth of Investigation)
`doi_index` por vóxel (Li & Oldenburg 1999): valores altos = el modelo
depende del modelo de referencia, no de los datos. Use el modo
`doi_reliable` del visor 3D para ocultar vóxeles no resueltos.

### Profundidades
La profundidad del **pico** de densidad es más confiable que el centroide
del cuerpo recuperado: la inversión suaviza en profundidad (smearing) y el
centroide se arrastra hacia abajo. Validado con esfera sintética a 400 m:
error del pico < 15 %.

---

## 6. Límites honestos del flujo

- El modelo de densidad **no** es una estimación de recursos JORC/NI 43-101;
  es un insumo de exploración temprana.
- Validado a escala local (< 10 km). A escala regional se requiere
  separación regional-residual (`remove_regional=true`) y restricciones
  geológicas externas — la profundidad es ambigua sin ellas.
- Con no-negatividad estricta (`density_min=2.6`) el solver LSQR+clip puede
  degradar el misfit en cuerpos compactos; el default v2 (`density_min=0.0`)
  permite contrastes negativos.
- La TC por prismas usa masa puntual en campo lejano; en terreno abrupto
  (>500 m de relieve dentro del radio) valide con un TC dedicado.

## 7. Interoperabilidad

`model.msh` + `model.den` siguen el formato UBC-GIF (GRAV3D), sin headers
de comentario, legibles directamente por SimPEG:

```python
import discretize
mesh = discretize.TensorMesh.read_UBC("model.msh")
model = mesh.read_model_UBC("model.den")   # densidades absolutas t/m³ (aire = -9999)
```

También se exporta `block_model_core.vtr` (ParaView/Leapfrog) y
`block_model.parquet` (schema v4.0).
