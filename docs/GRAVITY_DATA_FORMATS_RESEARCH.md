# Investigación de Formatos de Datos Gravimétricos: Preparación para TerraQuantum CSV v1

Este documento sintetiza la investigación técnica sobre las salidas de datos de diversos equipos gravimétricos (tradicionales y cuánticos) de la industria. Su propósito es establecer las bases para el desarrollo del futuro estándar de importación **TerraQuantum Gravity CSV v1**. 

*Nota: Esta investigación no define la implementación del importador, sino que actúa como documento preparatorio de la Fase 5.1.*

---

## 1. ¿Qué entrega realmente un gravímetro?

Es vital establecer que **un gravímetro no entrega un modelo 3D del subsuelo ni identifica minerales directamente**. Un gravímetro es un sensor de alta precisión que entrega:

*   **Aceleración de la gravedad ($g$)**: Medición de la fuerza gravitatoria en un punto y tiempo específicos.
*   Puede ser **Gravedad Absoluta** (el valor real de $g$) o **Gravedad Relativa** (la diferencia de $g$ respecto a un punto base o momento anterior).
*   **Anomalías**: En sistemas integrados o post-procesados, puede entregar valores de *Anomalía de Bouguer* o *Anomalía de Aire Libre*.
*   **Datos Crudos / Corregidos**: Lecturas de hardware brutas junto a datos corregidos por mareas, deriva, tilt, etc.

## 2. Columnas Importantes en Formatos de Exportación

Basado en el análisis de las salidas de equipos estándar (como Scintrex CG-6 y Micro-g LaCoste FG5) y cuánticos (como Exail AQG y Atomionics GRAVIO), las columnas más comunes y valiosas son:

| Columna | Descripción / Uso |
| :--- | :--- |
| `station_id` | Identificador único de la estación o punto de lectura. |
| `timestamp` | Fecha y hora exactas de la medición (crítico en corrección de mareas/deriva). |
| `lat` / `lon` / `elevation_m` | Coordenadas espaciales absolutas (o GPS crudo). |
| `x_m` / `y_m` / `z_m` | Coordenadas locales proyectadas (usadas internamente en TerraQuantum). |
| `g_raw` | Gravedad instrumental bruta, sin correcciones aplicadas. |
| `g_corrected` / `g` | Gravedad procesada/corregida lista para la inversión. |
| `gravity_anomaly` | Diferencia respecto a la gravedad teórica (Bouguer o Aire Libre). |
| `unit` | mGal, µGal o m/s². Vital para no mezclar escalas. |
| `uncertainty` | Incertidumbre o desviación estándar de la lectura (SD). |
| `instrument_id` | Número de serie o tipo de sensor. |
| `temperature_c` / `pressure_hpa` | Variables ambientales que influyen en el instrumento o las correcciones. |
| `quality_flag` | Indicador booleano o código (ej. lecturas rechazadas, inestabilidad). |
| Correcciones Específicas | `drift_correction`, `tide_correction`, `tilt_correction`, `terrain_correction`, `bouguer_correction`, `free_air_correction`. |

## 3. Unidades de Medida Estándar

En la industria geofísica y en los *datasheets* de los sensores, se observan tres unidades fundamentales:

1.  **m/s² (metros por segundo al cuadrado)**: Unidad del Sistema Internacional (SI). 1 m/s² = 100,000 mGal. Rara vez se usa en crudo para la exploración porque las variaciones geológicas son minúsculas.
2.  **Gal y mGal (miligal)**: La unidad histórica estándar. 1 Gal = 1 cm/s². La gravedad terrestre promedio es ~980,000 mGal. La exploración minera busca anomalías en el rango de los mGal.
3.  **µGal (microgal)**: Usado por gravímetros de alta precisión (como los absolutos o cuánticos). 1 µGal = 0.001 mGal. 

**Tabla de Conversiones Técnicas:**
*   1 Gal = 0.01 m/s²
*   1 mGal = 0.00001 m/s²
*   1 µGal = 0.00000001 m/s²
*   1 uGal = 0.00000001 m/s²

**Recomendación Preliminar de Unidades:**
La unidad interna futura recomendada para TerraQuantum Gravity CSV v1 será **m/s²**, pero el importador debe aceptar mGal, µGal y uGal y convertirlos.

## 4. Correcciones Comunes en Datos Brutos

Un dato $g$ sin corregir no sirve para exploración. Los equipos tradicionales y las suites de procesamiento aplican:

*   **Marea Terrestre (Earth Tide)**: Efecto gravitatorio de la Luna y el Sol.
*   **Deriva (Drift)**: Corrientes de relajación en resortes mecánicos o cuarzo. (Ausente en gravímetros absolutos y cuánticos).
*   **Inclinación (Tilt)**: Compensación si el equipo no estaba perfectamente nivelado.
*   **Temperatura y Presión Atmosférica**: Cambios que afectan la masa de aire sobre el sensor o la electrónica.
*   **Aire Libre (Free Air)**: Corrección por la distancia al centro de la Tierra (elevación).
*   **Bouguer**: Corrección por la masa de roca existente entre la estación y el elipsoide de referencia.
*   **Terreno**: Compensación por la topografía circundante (valles y montañas).

## 5. Diferencias Clave: Gravímetros Cuánticos vs. Tradicionales

Se analizaron modelos clave: **Exail (Muquans) AQG**, **Atomionics GRAVIO**, **Nomad Atomics**, frente a **Scintrex CG-5/CG-6** (relativo de resorte) y **Micro-g LaCoste FG5** (absoluto de caída libre).

| Característica | Cuánticos (ej. AQG, GRAVIO) | Tradicionales Relativos (ej. CG-6) | Tradicionales Absolutos (ej. FG5) |
| :--- | :--- | :--- | :--- |
| **Tecnología** | Interferometría de átomos fríos. | Resortes de cuarzo / metal. | Caída libre de masa macroscópica. |
| **Tipo de Medición** | Absoluta. | Relativa (requiere estación base). | Absoluta. |
| **Deriva Instrumental** | Reduce o elimina la deriva instrumental de largo plazo típica de gravímetros relativos. | Significativa (requiere cierres de lazos). | Nula. |
| **Correcciones de Datos** | Sigue requiriendo correcciones ambientales, control de calidad y procesamiento según campaña. | Mareas, presión, tilt, **deriva instrumental obligatoria**. | Mareas, presión, etc. |
| **Portabilidad y Uso** | Naciendo versiones dinámicas (GRAVIO en SUVs). Uso estático o dinámico. | Muy portátiles, mochilas. Uso estático punto a punto. | Equipos de laboratorio estáticos, poco portátiles. |

## 6. Implicancias para el Diseño en TerraQuantum

Antes de construir el importador y definir el CSV v1, el sistema backend y frontend de TerraQuantum deben considerar:

1.  **Flexibilidad de Ingesta**: TerraQuantum debe soportar un CSV "simple" (solo coordenadas y $g$) para pruebas sintéticas, y un CSV "profesional" (con metadata completa y flags) para operaciones de campo reales.
2.  **Conversión de Unidades**: Se debe forzar o validar la columna `unit`. Si el usuario provee mGal y el backend espera m/s², o viceversa, la validación sintética colapsará.
3.  **Trazabilidad y Semántica de Variables**: Es imperativo mantener una separación estricta entre:
    *   **`g_raw`**: Lectura instrumental bruta sin correcciones.
    *   **`g_corrected`**: Gravedad con correcciones ambientales aplicadas (pero no es una anomalía).
    *   **Gravedad Absoluta**: Valor real de la aceleración.
    *   **Anomalía de Aire Libre**: Gravedad corregida por elevación.
    *   **Anomalía de Bouguer**: Gravedad corregida por elevación y masa de roca.
    *   **`gravity_anomaly`**: Diferencia respecto a la gravedad teórica.
    TerraQuantum debe evitar mezclar estas columnas sin declaración explícita.
4.  **Advertencia Técnica sobre la columna `g`**: El backend actual recibe una columna llamada `g`, pero para inversión geofísica seria el estándar debe declarar si esa `g` representa:
    *   gravedad absoluta
    *   gravedad corregida
    *   anomalía
    *   residual
    *   dato sintético/demo
5.  **Metadata de Calidad**: Guardar la incertidumbre (`uncertainty`) y el `instrument_id`. Si falta el timestamp o el equipo, el sistema debe arrojar una advertencia (Warning), pero no necesariamente bloquear.
6.  **Comunicación UI**: Permitir el uso de datos sintéticos o de demostración, pero deben quedar marcados visualmente como "Demo" en la interfaz. El frontend nunca debe afirmar que una anomalía gravimétrica confirma mineral, sino presentarlo como "Modelo de densidad" o "Anomalía modelada".

## 7. Recomendación Preliminar para TerraQuantum Gravity CSV v1

*Pendiente de validación e implementación.*

Se proponen los siguientes niveles de soporte en el futuro importador:

**Formato Mínimo Viable (Demo/Sintético):**
```csv
station_id,x_m,y_m,z_m,g,unit
```

**Formato Recomendado (Uso General):**
```csv
station_id,x_m,y_m,z_m,g,unit,uncertainty,quality_flag
```

**Formato Profesional (Completo):**
```csv
station_id,timestamp,lat,lon,elevation_m,x_m,y_m,z_m,g_raw,g_corrected,gravity_anomaly,unit,uncertainty,instrument_id,temperature_c,pressure_hpa,quality_flag
```

## 8. Riesgos Técnicos (Limitaciones Identificadas)

*   **Formatos Propietarios**: Empresas como Atomionics o Nomad Atomics entregan el procesamiento end-to-end, por lo que el CSV final que llegue a TerraQuantum podría ser un producto derivado y no los crudos del sensor.
*   **Variables Mezcladas**: Confusión recurrente en el cliente sobre si provee *Gravedad Absoluta*, *Anomalía de Aire Libre* o *Anomalía de Bouguer*.
*   **Proyecciones de Coordenadas**: Riesgo grave si se suben `lat`/`lon` sin declarar el Datum, o si `x_m`/`y_m` asumen un EPSG no coincidente con el modelo de bloques.
*   **Incertidumbre Cero**: Si los datos reales se sobreinterpretan (confundir ruido del equipo con mineral).
*   **Falsos Positivos Visuales**: Riesgo de que la UI induzca a los ingenieros de mina a tratar el modelo gravimétrico invertido como "perforación confirmada".

## 9. Próximo Paso Recomendado

Concluida esta fase de investigación, la recomendación técnica formal (Fase 5.2) es proceder con la creación y aprobación de:
`docs/TERRAQUANTUM_GRAVITY_CSV_V1.md`

### Qué debe pasar a Fase 5.2
*   **Columnas mínimas**: `station_id`, `x_m`, `y_m`, `z_m`, `g`, `unit`.
*   **Columnas recomendadas**: `uncertainty`, `quality_flag`.
*   **Columnas profesionales**: `timestamp`, `lat`, `lon`, `elevation_m`, `g_raw`, `g_corrected`, `gravity_anomaly`, `instrument_id`, temperatura, presión, etc.
*   **Unidad interna**: `m/s²`.
*   **Prioridad**: Reglas de prioridad entre `gravity_anomaly`, `g_corrected`, `g` y `g_raw`.
*   **Metadata de importación**: Almacenamiento de metadatos globales del archivo.
*   **Errores bloqueantes**: Carencia de coordenadas o unidad de medida irresoluble.
*   **Warnings no bloqueantes**: Falta de timestamps, incertidumbre o IDs de equipo.

Este futuro documento definirá las reglas estrictas de parseo, los schemas de pydantic en el backend, y el manejo de los estados en la interfaz.

---
## 10. Bibliografía técnica y fuentes verificables

| Fuente / Equipo | Tipo de fuente | Qué respalda | Enlace o referencia | Nivel de confianza |
| :--- | :--- | :--- | :--- | :--- |
| Exail / Muquans AQG | Datasheets y manuales técnicos | Datos crudos, variables atmosféricas y correcciones. | [Exail AQG](https://www.exail.com/products/absolute-quantum-gravimeter/) | Alto |
| Atomionics GRAVIO | Artículos técnicos y web oficial | Gravimetría dinámica, eliminación de deriva de largo plazo. | [Atomionics GRAVIO](https://atomionics.com/) | Medio (Formatos propietarios) |
| Nomad Atomics | Web oficial y especificaciones | Estabilidad temporal, mediciones drift-free absolutas. | [Nomad Atomics](https://nomadatomics.com/) | Medio (Formatos propietarios) |
| Scintrex CG-6 | Manual de operación | Salidas relativas, mGal, correcciones por tilt y deriva. | [Scintrex CG-6](https://scintrexltd.com/) | Alto |
| Micro-g LaCoste FG5 / FG5-X | Manuales del software "g" | Salidas de gravedad absoluta, incertezas, µGal, scatter. | [Micro-g LaCoste](https://microglacoste.com/) | Alto |
| `gravitools` | Herramienta académica/comunitaria | Parseo de archivos crudos de AQG y estructuración de outputs. | [PyPI gravitools](https://pypi.org/project/gravitools/) | Alto |
