# TerraQuantum Gravity CSV v1 - Estándar Oficial

## 1. Propósito del estándar
TerraQuantum Gravity CSV v1 define el formato oficial estandarizado para la importación de mediciones gravimétricas hacia la plataforma TerraQuantum. Este estándar está diseñado para admitir datos reales de campo (gravimetría cuántica o tradicional), datos profesionales con metadatos completos y conjuntos de datos de demostración o sintéticos rigurosamente controlados.

## 2. Principio técnico
La base de este estándar reconoce que:
*   Un gravímetro **no entrega directamente un modelo 3D del subsuelo** ni confirma la presencia de mineralización.
*   El equipo entrega mediciones de gravedad (absoluta o relativa), anomalías, o datos crudos/corregidos medidos puntualmente por estación.
*   El sistema TerraQuantum toma estas lecturas tabulares y las convierte en `observations`.
*   Posteriormente, el motor físico del backend ejecuta una inversión geofísica 3D sobre estas observaciones.
*   El resultado final es un **modelo preliminar de densidad o anomalía modelada**, el cual sirve como herramienta de interpretación geofísica, pero *nunca* como confirmación directa de mineral.

## 3. Compatibilidad con backend actual
Actualmente, el motor de inversión en el backend de TerraQuantum espera una lista estructurada de diccionarios:
```json
observations = [
  { "x_m": 100.0, "y_m": 200.0, "z_m": 50.0, "g": 0.0000015 }
]
```
El estándar **CSV v1 actúa como una capa de preprocesamiento y validación anterior** a esta estructura. Su objetivo es asegurar la calidad, transformar unidades de forma segura y estructurar la metainformación antes de inyectar las observaciones finales al motor de cálculo.

## 4. Unidad interna oficial
Para garantizar la integridad y coherencia matemática en los algoritmos de inversión de TerraQuantum, la unidad interna oficial de procesamiento es:
**`m/s²` (metros por segundo al cuadrado)**

Las conversiones estrictas adoptadas por la plataforma son:
*   1 Gal = 0.01 m/s²
*   1 mGal = 0.00001 m/s²
*   1 µGal = 0.00000001 m/s²
*   1 uGal = 0.00000001 m/s²

## 5. Unidades aceptadas
El archivo CSV provisto por el usuario o cliente **debe** declarar obligatoriamente la unidad de medida utilizada. Las unidades válidas aceptadas por el parser son exclusivamente:
*   `m/s2`
*   `m/s²`
*   `mGal`
*   `uGal`
*   `µGal`

Cualquier otra cadena (ej. *mgals*, *ug*, vacíos) será considerada como un **error bloqueante**.

---

## 6. Formato mínimo obligatorio
Para habilitar una importación exitosa, especialmente en casos sintéticos o demostraciones rápidas, el formato mínimo requerido es:
`station_id,x_m,y_m,z_m,g,unit,gravity_type`

*Nota: `gravity_type` puede venir como columna del CSV o como metadata global de importación, pero en modo estricto debe existir antes de ejecutar la inversión.*

| Nombre | Tipo | Obligatorio | Descripción | Ejemplo | Regla de validación |
| :--- | :--- | :--- | :--- | :--- | :--- |
| `station_id` | String | Sí | Identificador único de la estación. | `ST-001` | No vacío. |
| `x_m` | Float | Sí | coordenada horizontal local X, en metros. | `500.0` | Numérico, no NaN/Inf. |
| `y_m` | Float | Sí | profundidad positiva hacia abajo, en metros. | `0.0` | Numérico, no NaN/Inf. |
| `z_m` | Float | Sí | coordenada horizontal local Z, en metros. | `150.5` | Numérico, no NaN/Inf. |
| `g` | Float | Sí | Valor de lectura gravimétrica. | `0.245` | Numérico, no NaN/Inf. |
| `unit` | String | Sí | Unidad física de la columna `g`. | `mGal` | Restringido a permitidos. |
| `gravity_type` | String | Sí en modo estricto | declara qué representa la gravedad usada. | `bouguer_anomaly` | debe pertenecer a los valores permitidos. |

*Nota sobre la convención espacial: El backend actual de TerraQuantum interpreta `y_m` como profundidad positiva hacia abajo. Si los datos de campo vienen como Este/Norte/Elevación, deben ser transformados antes a la convención local de TerraQuantum.*

---

## 7. Formato recomendado
Se incentiva a los usuarios a proveer un formato con metadatos de calidad, ideal para trabajos de campo:
`station_id,x_m,y_m,z_m,g,unit,uncertainty,quality_flag,gravity_type`

*   **`uncertainty`**: Mejora significativamente el desempeño del motor QA/QC ponderando las inversiones. Su ausencia arrojará un *warning*.
*   **`quality_flag`**: Permite descartar automáticamente mediciones ruidosas. Su ausencia arrojará un *warning*.

---

## 8. Formato profesional
Para campañas reales y gravimetría cuántica (donde el tracking atmosférico es vital), el formato soportado incluye:
`station_id,timestamp,lat,lon,elevation_m,x_m,y_m,z_m,g_raw,g_corrected,gravity_anomaly,unit,uncertainty,instrument_id,temperature_c,pressure_hpa,quality_flag,gravity_type`

*   `timestamp`: Fecha y hora ISO-8601 de la medición.
*   `lat` / `lon`: Coordenadas WGS84 o equivalentes sin proyectar.
*   `elevation_m`: Elevación absoluta sobre el nivel del mar.
*   `g_raw`: Gravedad bruta instrumental.
*   `g_corrected`: Gravedad con correcciones de marea, deriva, etc.
*   `gravity_anomaly`: Anomalía de gravedad final (Bouguer/Aire libre).
*   `instrument_id`: Número de serie o modelo del gravímetro.
*   `temperature_c` / `pressure_hpa`: Variables ambientales al momento de la captura.

---

## 9. Semántica obligatoria de gravedad
TerraQuantum diferencia conceptualmente las etapas de la gravedad:
*   **`g_raw`**: Lectura instrumental cruda. No apta para inversión sin proceso previo.
*   **`g_corrected`**: Gravedad medida a la que se le ha aplicado reducción por factores instrumentales o ambientales.
*   **Gravedad Absoluta**: Aceleración total medida respecto al cero absoluto.
*   **Anomalía de Aire Libre**: Gravedad corregida por la distancia al centro de masa terrestre.
*   **Anomalía de Bouguer**: Anomalía corregida adicionalmente por la masa rocosa intermedia.
*   **`gravity_anomaly`**: Diferencia entre la medición corregida y la gravedad teórica referencial.
*   **Residual**: Anomalía tras la remoción de la tendencia regional.
*   **Dato demo/sintético**: Información fabricada matemáticamente para pruebas.

*Nota:* Nombrar una columna simplemente `g` resulta **ambiguo**, por lo que es obligatorio declarar su significado.

---

## 10. Campo obligatorio `gravity_type`
Para resolver la ambigüedad de la columna `g` o `gravity_anomaly`, el importador exigirá que se declare qué tipo de procesamiento tiene la data. Esto puede ser mediante una columna adicional o metadato global inyectado al subir el archivo. 

La variable se llamará `gravity_type` y sus valores permitidos son:
*   `absolute_gravity`
*   `corrected_gravity`
*   `free_air_anomaly`
*   `bouguer_anomaly`
*   `residual_anomaly`
*   `synthetic_demo`

Si `gravity_type` falta, será un **error bloqueante** en modo estricto, o un *warning fuerte* en modos permisivos.

---

## 11. Prioridad de ingesta de columnas
En casos donde un archivo profesional contenga múltiples columnas gravimétricas, el futuro importador seleccionará automáticamente qué columna enviar al backend siguiendo este orden de prioridad:
1.  `gravity_anomaly`
2.  `g_corrected`
3.  `g`
4.  `g_raw` *(Solo si no hay otra opción, y levantará un warning fuerte indicando que los resultados carecerán de fiabilidad geológica).*

El importador deberá registrar obligatoriamente en la metainformación final cuál de estas columnas fue utilizada.

---

## 12. Reglas de validación bloqueantes (Errores)
El importador rechazará el procesamiento del archivo si se detecta:
*   Archivo vacío o ilegible.
*   Menos de 10 observaciones válidas en total.
*   Ausencia de identificador `station_id` o celda vacía en filas activas.
*   Falta de columnas del Formato Mínimo Obligatorio.
*   Valores en `x_m`, `y_m`, `z_m` que no sean numéricos.
*   Valor de `g` (o la columna de gravedad seleccionada por prioridad) no numérico.
*   Presencia de `NaN` o valores infinitos (`Inf`) en coordenadas o gravedad.
*   Coordenadas espaciales 3D (`x_m`, `y_m`, `z_m`) exactamente duplicadas entre dos o más filas.
*   Columna `unit` faltante o con valor no soportado.
*   Columna `gravity_type` faltante (cuando se requiera por modo estricto).
*   Señal de gravedad igual a cero absoluto (o casi cero homogéneo) en todas las observaciones del set.
*   Uso de `g_raw` exclusivo, sin declaración explícita de aceptación por el usuario.

---

## 13. Warnings no bloqueantes
El importador registrará advertencias pero permitirá continuar el flujo si detecta:
*   Ausencia de `uncertainty` (se asumirá error homogéneo por defecto).
*   Ausencia de `timestamp`.
*   Ausencia de `instrument_id`.
*   Ausencia de `quality_flag`.
*   Baja cobertura espacial o arreglo colineal no apto para volumetría 3D.
*   Rango dinámico de la señal excesivamente bajo (varianza casi nula).
*   Uso inyectado de `g_corrected` en lugar de una verdadera `gravity_anomaly`.
*   Detección de bandera `synthetic_demo` (se advertirá que los datos no son reales).
*   Presencia de `lat`/`lon` sin declaración de EPSG o Datum.
*   Uso exclusivo de coordenadas locales sin descripción de origen geográfico real.

---

## 14. Metadata de importación
El importador debe ensamblar y resguardar en base de datos la siguiente estructura JSON como registro trazable:

```json
import_metadata = {
  "source_file": "...",
  "schema_version": "TerraQuantum Gravity CSV v1",
  "unit_original": "...",
  "unit_internal": "m/s²",
  "gravity_column_used": "...",
  "gravity_type": "...",
  "conversion_applied": true,
  "row_count": 0,
  "valid_rows": 0,
  "rejected_rows": 0,
  "warnings": [],
  "errors": [],
  "is_demo": false
}
```

---

## 15. Salida normalizada hacia backend
Tras el parseo, conversión y limpieza, el módulo importador debe emitir una lista de diccionarios hacia el motor de geofísica, garantizando que `g` se encuentre convertida estrictamente a **m/s²**.

```json
observations = [
  {
    "x_m": 0.0,
    "y_m": 0.0,
    "z_m": 0.0,
    "g": 0.000001
  }
]
```

---

## 16. Ejemplo mínimo válido
```csv
station_id,x_m,y_m,z_m,g,unit,gravity_type
ST01,100,100,50,0.15,mGal,bouguer_anomaly
ST02,200,100,50,0.18,mGal,bouguer_anomaly
ST03,300,100,50,0.22,mGal,bouguer_anomaly
ST04,400,100,50,0.30,mGal,bouguer_anomaly
ST05,500,100,50,0.25,mGal,bouguer_anomaly
ST06,100,200,50,0.12,mGal,bouguer_anomaly
ST07,200,200,50,0.14,mGal,bouguer_anomaly
ST08,300,200,50,0.20,mGal,bouguer_anomaly
ST09,400,200,50,0.28,mGal,bouguer_anomaly
ST10,500,200,50,0.22,mGal,bouguer_anomaly
```

## 17. Ejemplo recomendado válido
```csv
station_id,x_m,y_m,z_m,g,unit,uncertainty,quality_flag,gravity_type
ST01,100,100,50,0.15,mGal,0.01,OK,bouguer_anomaly
ST02,200,100,50,0.18,mGal,0.012,OK,bouguer_anomaly
ST03,300,100,50,0.22,mGal,0.009,OK,bouguer_anomaly
ST04,400,100,50,0.30,mGal,0.015,OK,bouguer_anomaly
ST05,500,100,50,0.25,mGal,0.02,WARNING,bouguer_anomaly
ST06,100,200,50,0.12,mGal,0.01,OK,bouguer_anomaly
ST07,200,200,50,0.14,mGal,0.01,OK,bouguer_anomaly
ST08,300,200,50,0.20,mGal,0.008,OK,bouguer_anomaly
ST09,400,200,50,0.28,mGal,0.011,OK,bouguer_anomaly
ST10,500,200,50,0.22,mGal,0.01,OK,bouguer_anomaly
```

## 18. Ejemplo profesional válido
```csv
station_id,timestamp,lat,lon,elevation_m,x_m,y_m,z_m,g_raw,g_corrected,gravity_anomaly,unit,uncertainty,instrument_id,temperature_c,pressure_hpa,quality_flag,gravity_type
ST01,2026-05-01T10:00:00Z,-23.5,-68.2,2500,100,0,100,978000.1,978000.15,0.15,mGal,0.01,CG6-1024,15.2,760,OK,bouguer_anomaly
ST02,2026-05-01T10:15:00Z,-23.501,-68.2,2502,200,0,100,978000.12,978000.18,0.18,mGal,0.01,CG6-1024,15.4,760,OK,bouguer_anomaly
ST03,2026-05-01T10:30:00Z,-23.502,-68.2,2505,300,0,100,978000.15,978000.22,0.22,mGal,0.01,CG6-1024,15.5,759,OK,bouguer_anomaly
ST04,2026-05-01T10:45:00Z,-23.503,-68.2,2503,400,0,100,978000.2,978000.30,0.30,mGal,0.01,CG6-1024,15.8,758,OK,bouguer_anomaly
ST05,2026-05-01T11:00:00Z,-23.504,-68.2,2501,500,0,100,978000.18,978000.25,0.25,mGal,0.01,CG6-1024,16.0,758,OK,bouguer_anomaly
ST06,2026-05-01T11:15:00Z,-23.5,-68.201,2500,100,0,200,978000.08,978000.12,0.12,mGal,0.01,CG6-1024,16.2,758,OK,bouguer_anomaly
ST07,2026-05-01T11:30:00Z,-23.501,-68.201,2502,200,0,200,978000.1,978000.14,0.14,mGal,0.01,CG6-1024,16.3,757,OK,bouguer_anomaly
ST08,2026-05-01T11:45:00Z,-23.502,-68.201,2504,300,0,200,978000.16,978000.20,0.20,mGal,0.01,CG6-1024,16.5,757,OK,bouguer_anomaly
ST09,2026-05-01T12:00:00Z,-23.503,-68.201,2503,400,0,200,978000.22,978000.28,0.28,mGal,0.01,CG6-1024,16.7,756,OK,bouguer_anomaly
ST10,2026-05-01T12:15:00Z,-23.504,-68.201,2501,500,0,200,978000.17,978000.22,0.22,mGal,0.01,CG6-1024,16.8,756,OK,bouguer_anomaly
```

## 19. Ejemplos inválidos

**Error: Menos de 10 filas**
```csv
station_id,x_m,y_m,z_m,g,unit,gravity_type
ST01,100,100,50,0.15,mGal,bouguer_anomaly
ST02,200,100,50,0.18,mGal,bouguer_anomaly
```

**Error: Unidad faltante (`unit` no declarada)**
```csv
station_id,x_m,y_m,z_m,g,gravity_type
ST01,100,100,50,0.15,bouguer_anomaly
... (hasta 10 filas)
```

**Error: Unidad desconocida**
```csv
station_id,x_m,y_m,z_m,g,unit,gravity_type
ST01,100,100,50,0.15,mgals,bouguer_anomaly
... (hasta 10 filas)
```

**Error: Gravedad no numérica**
```csv
station_id,x_m,y_m,z_m,g,unit,gravity_type
ST01,100,100,50,N/A,mGal,bouguer_anomaly
... (hasta 10 filas)
```

**Error: `gravity_type` faltante**
```csv
station_id,x_m,y_m,z_m,g,unit
ST01,100,100,50,0.15,mGal
... (hasta 10 filas)
```

**Error: Coordenadas duplicadas exactas**
```csv
station_id,x_m,y_m,z_m,g,unit,gravity_type
ST01,100,100,50,0.15,mGal,bouguer_anomaly
ST02,100,100,50,0.18,mGal,bouguer_anomaly
... (hasta 10 filas)
```

**Error: Mezcla de `g_raw` y `gravity_anomaly` sin declarar tipo en modo ambiguo**
```csv
station_id,x_m,y_m,z_m,g_raw,gravity_anomaly,unit
ST01,100,100,50,978000.1,0.15,mGal
... (hasta 10 filas)
```
*(Falta indicar cuál tiene prioridad o el `gravity_type` general si no está automatizado en el importador).*

---

## 20. Relación con QA/QC existente
Los datos validados e importados a través de este estándar garantizarán el correcto funcionamiento y la fidelidad de las actuales rutinas del backend de TerraQuantum, específicamente:
*   `validate_geophysics_input`
*   `build_observation_qaqc_report`
*   Flujo visual de **Observed vs Modeled**
*   **Residual Map**
*   **Uncertainty Diagnostics**
*   **Sensor Quality Flags**
*   **Technical Summary**

*(Nota: Esta fase documentaria no modifica dicho código).*

---

## 21. Reglas de comunicación visual (UI)
Una vez que TerraQuantum ingiera datos reales a través de este CSV, el frontend deberá acatar estrictamente las siguientes reglas semánticas:
*   **Prohibido el uso de:** *"Mineral Confirmado"*, *"Cuerpo de Cobre hallado"*, o sentencias absolutistas geológicas.
*   **Textos recomendados:** *"Anomalía modelada"*, *"Modelo preliminar de densidad"*, *"Target de perforación recomendado"*, *"Modelo preliminar de contraste de densidad"*.
*   Si `gravity_type == synthetic_demo`, la pantalla debe rotular el modelo explícitamente con el tag **"DEMO"**.
*   Si la columna `uncertainty` faltaba en el archivo y fue auto-llenada, la interfaz debe mostrar una advertencia: *"Incertidumbre asumida; diagnóstico QA/QC condicionado"*.

---

## 22. Alcance de Fase 5.2
*   **Este documento única y exclusivamente define el estándar normativo.**
*   *No implementa importador.*
*   *No modifica APIs.*
*   *No modifica schemas Pydantic.*
*   *No modifica el frontend.*

---

## 23. Próximas fases
Las siguientes fases de ingeniería en el roadmap para materializar este estándar son:
*   **Fase 5.3** — Crear ejemplos de archivos válidos e inválidos reales (assets en CSV).
*   **Fase 5.4** — Crear importador backend CSV (servicios y Pydantic schemas).
*   **Fase 5.5** — Extensión para soporte Excel/Parquet.
*   **Fase 5.6** — UI: Preview/QA estadístico del archivo antes de invertir.
*   **Fase 5.7** — Conectar importador validado con ruta `/geophysics-invert`.
*   **Fase 5.8** — UI para componente drag & drop de subida de archivo.
*   **Fase 5.9** — Sistema de persistencia de archivo original en bucket + metadata.
