# Mock Data para TerraQuantum Gravity CSV v1

**Propósito:**
Esta carpeta contiene datos sintéticos y controlados (mocks) para ser utilizados exclusivamente en el desarrollo y testing (Fase 5.4) del futuro importador del backend de TerraQuantum. Todos los datos están formateados de acuerdo con el estándar técnico **TerraQuantum Gravity CSV v1** (Fase 5.2).

**⚠️ Recordatorio Crítico:**
*   Estos archivos **no representan modelos reales** del subsuelo.
*   Fueron fabricados matemáticamente para validación de software.
*   Bajo ningún concepto las anomalías contenidas aquí afirman o confirman "mineral".

## Archivos Válidos

*   `valid_minimal_bouguer_mgal.csv`: Formato mínimo requerido (7 columnas). Datos en `mGal` simulando anomalías de Bouguer sobre una grilla de superficie (`y_m`=0).
*   `valid_recommended_bouguer_mgal.csv`: Formato recomendado añadiendo columnas de QA/QC (`uncertainty` y `quality_flag`).
*   `valid_professional_bouguer_mgal.csv`: Formato profesional completo con 18 columnas simulando mediciones de campo, metadatos atmosféricos y priorización jerárquica de `gravity_anomaly`.
*   `valid_synthetic_demo_ms2.csv`: Formato mínimo con valores y unidades expresadas directamente en la unidad interna oficial (`m/s2`), declarado explícitamente como demo sintética.

## Archivos Inválidos (Tests de Errores Bloqueantes)

| Archivo | Motivo Esperado de Fallo |
| :--- | :--- |
| `invalid_missing_unit.csv` | Error bloqueante: Falta la columna de unidad (`unit`), impidiendo cualquier conversión de escala. |
| `invalid_missing_gravity_type.csv` | Error bloqueante: Falta el metadato obligatorio `gravity_type` en modo estricto. |
| `invalid_less_than_10_rows.csv` | Error bloqueante: Menos de 10 observaciones válidas. |
| `invalid_duplicate_coordinates.csv` | Error bloqueante: Coordenadas espaciales 3D (`x_m`, `y_m`, `z_m`) exactamente duplicadas. |
| `invalid_unknown_unit.csv` | Error bloqueante: Unidad desconocida (`mgals` en lugar de `mGal`). |
| `invalid_non_numeric_g.csv` | Error bloqueante: Valor de gravedad (`g`) no numérico (contiene `N/A`). |
| `invalid_all_zero_signal.csv` | Error bloqueante: Señal cero o casi cero homogénea, impidiendo la inversión numérica. |
| `invalid_g_raw_only_without_acceptance.csv` | Error bloqueante: Uso exclusivo de lectura cruda (`g_raw`) sin declaración de `gravity_anomaly` ni aceptación explícita. |
