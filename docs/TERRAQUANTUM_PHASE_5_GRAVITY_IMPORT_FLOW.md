# Flujo de Importación Gravimétrica (Fase 5) - TerraQuantum

## 1. Propósito de la Fase 5
La Fase 5 habilita la ingesta estandarizada, validada y trazable de datos gravimétricos a través del estándar oficial **TerraQuantum Gravity CSV v1**. Esta fase permite al ecosistema transicionar desde datos 100% pre-empaquetados (demos sintéticas) hacia un pipeline donde el analista carga datos medidos en terreno o modelados externamente, los depura e inspecciona visualmente y orquesta la inversión matemática nativa de TerraQuantum sobre ellos. Todo el ciclo garantiza consistencia física, conversiones unificadas y persistencia auditable.

## 2. Flujo Completo

El siguiente diagrama textual ilustra el viaje del archivo desde la selección en el cliente hasta la visualización final del modelo geofísico en 3D:

```text
CSV Gravity v1
  ↓
[Frontend] /gravity-import/preview
  ↓
[Backend] import_gravity_csv_v1
  ↓
[Backend] Observations Normalizadas (Unidad interna m/s²)
  ↓
[Frontend] Muestra resumen visual interactivo y warnings técnicos
  ↓
[Frontend] /gravity-import/invert (Envía el CSV entero con validación estricta)
  ↓
[Backend] Ingesta validada → Construcción de GeophysicsInvertInput
  ↓
[Backend] run_geophysics_inversion (Motor Físico / Fortran-C)
  ↓
[Backend] Generación de block_model.parquet y Reportes
  ↓
[Frontend] Carga del modelo 3D (Botón interactivo en UI)
  ↓
[Backend] Exportación ZIP (Incluye source_gravity.csv y metadatos)
```

## 3. Archivos Principales Backend

El ecosistema Python / FastAPI gestiona la validación científica y el puente con el motor físico:

- `schemas/gravity_import_schema.py`: Define el contrato semántico y tipado estricto (Pydantic) de la Metadata de la importación y sus listados de `ObservationData`.
- `services/gravity_import_service.py`: Motor central de parsing y validación del CSV. Es el responsable de forzar la prioridad de ingesta gravimétrica y garantizar las transformaciones a unidades de SI.
- `api/gravity_import_api.py`: Capa de ruteo FastAPI que expone `/gravity-import/preview` (Validación preliminar rápida) y `/gravity-import/invert` (Procesamiento y delegación a Fortran).
- `core/block_model_store.py`: Orquestador de FileSystem para las corridas. Provee funciones para inyectar persistencia a los binarios, metadatos y ensamblaje de descargas ZIP.
- `scripts/validation/mock_data/gravity_csv_v1/`: Repositorio estático de CSVs usados para el control de calidad local (Mock Data).
- `scripts/validation/test_gravity_csv_v1.py`: Pruebas unitarias de parsing del servicio core contra las limitantes físicas.
- `scripts/validation/test_gravity_import_api.py`: Validaciones del endpoint de preview.
- `scripts/validation/test_gravity_import_invert_api.py`: Simulaciones del endpoint de Inversión y Proxy Frontend.
- `scripts/validation/test_gravity_import_persistence.py`: Evaluador de la escritura en disco y manejo concurrente (PermissionError).
- `scripts/validation/test_gravity_import_trace_export.py`: Auditor de integridad del empaquetado ZIP final y su soporte *Legacy*.

## 4. Archivos Principales Frontend

Next.js / React asegura la protección de los estados de interfaz y proxifica las descargas masivas de modelos:

- `componentes/GravityCsvPreviewPanel.tsx`: Componente base que permite la carga nativa (FileReader), selección de rigor estricto, análisis pre-vuelo y disparo final de la Inversión. 
- `lib/terraquantum/frontendApi.ts`: Consolidado de fetchers tipados y *type-guards* (para esquivar la regla `no-explicit-any`).
- `app/api/gravity-import/preview/route.ts`: Endpoint Next.js (Proxy intermedio) para ofuscar el servidor Python y canalizar el binario al Pre-Vuelo.
- `app/api/gravity-import/invert/route.ts`: Endpoint Next.js (Proxy intermedio) dedicado a disparar la Inversión.
- `DatosView.tsx`: Vista anfitriona donde conviven el explorador nativo y el panel del Preview de CSVs.

## 5. Qué hace el Importador (Backend)

La capa de ingesta en Python actúa como guardián estricto para proteger el motor de inversión, asegurando que:
- **Valida Unidades (`unit`)**: Lee el estándar (mGal, µGal, etc.).
- **Valida Tipos (`gravity_type`)**: Impide que anomalías de Bouguer se procesen como datos crudos bajo modo estricto.
- **Jerarquiza Columnas**: Automáticamente transita prioridades en caso de CSV desordenados (`gravity_anomaly > g_corrected > g > g_raw`).
- **Homologa Unidades Físicas**: Multiplica de inmediato hacia la escala interna requerida por Fortran (`m/s²`).
- **Bloquea Errores Críticos**: Rechaza nulos geográficos, faltas de Z y unidades mezcladas en el mismo CSV.
- **Informa (Warnings)**: Alerta por la ingesta de `g_raw` y de correcciones topográficas ignoradas.

## 6. Qué NO hace el Frontend

Para mantener *Single Source of Truth* y aislar la matemática pesada:
- **No convierte unidades**: Delega la multiplicación métrica a Python.
- **No valida física**: No audita límites espaciales ni de terreno.
- **No reensambla vectores**: Al invertir, transfiere todo el CSV binario en lugar del json parcial del `preview`.
- **No recalcula el Block Model**: Para visualizar en 3D, descarga celdas crudas terminadas desde FastAPI.
- **No afirma mineral confirmado**: Trata toda sugerencia geométrica como *"target preliminar"*, *"anomalía modelada"* o *"modelo de densidad"*.

## 7. Persistencia y Trazabilidad

A partir de la Fase 5.9, el ecosistema de TerraQuantum ahora es trazable *end-to-end*. Una corrida validada genera y encapsula permanentemente en su ruta `/runs/<run_id>/`:
1. `source_gravity.csv` (CSV Inmaculado tal como lo envió el cliente).
2. `gravity_import_metadata.json` (Forense de cómo se ingirió y transformó).
3. `inputs.json`
4. `observations.json`
5. `report.json`
6. `block_model.parquet`
7. `block_model_anomaly.parquet`

## 8. Exportación

La función de descarga ZIP (`export_project_run_zip`) incorpora incondicionalmente el gemelo digital de los datos iniciales. Si `source_gravity.csv` y sus metadatos existen en la corrida evaluada, se anexan nativamente en el paquete que descarga el usuario. Garantiza total reconstrucción histórica offline.

## 9. Tests de Validación

Para homologar la completitud y el cumplimiento técnico, existen las siguientes suites de calidad automáticas.

**Para Backend:**
```bash
cd C:\Users\marti\OneDrive\Documentos\TerraQuantum\terraquantum-backend
python scripts\validation\test_gravity_csv_v1.py
python scripts\validation\test_gravity_import_api.py
python scripts\validation\test_gravity_import_invert_api.py
python scripts\validation\test_gravity_import_persistence.py
python scripts\validation\test_gravity_import_trace_export.py
python -m compileall api schemas services core scripts
```

**Para Frontend:**
```bash
cd C:\Users\marti\OneDrive\Documentos\TerraQuantum\terraquantum-web
npm run lint
```

## 10. Estado Actual

El flujo de extremo a extremo está plenamente operativo. La plataforma ahora soporta la importación, validación, orquestación, inversión matemática, persistencia de estado y re-visualización de grillas gravimétricas 3D utilizando **Datos Sintéticos Estructurados (Mocks)** del estándar **TerraQuantum Gravity CSV v1**. 
Aún resta validar la ergonomía del flujo con exportaciones gravimétricas masivas y crudas emanadas directamente por equipos profesionales y proveedores del sector.

## 11. Limitaciones Pendientes

*   Aún no soporta `.xlsx` o flujos nativos en `Parquet` desde el cliente frontal.
*   Aún no es capaz de interpretar los encabezados propietarios estáticos de sondas/equipos comerciales sin un pre-proceso de limpieza.
*   El backend no implementa particionado nativo (streaming/chunks) para manejar archivos CSV superiores a 50MB desde el Proxy Next.js.
*   El endpoint de Inversión (`/gravity-import/invert`) es síncrono. Inversiones densas forzarán TimeOuts HTTP bajo Nginx.
*   El modelo geológico graficado continúa en una etapa visual primaria y rudimentaria.
*   La acción `DRILL` es estrictamente algorítmica y teórica, dictada sobre contrastes de densidad; no supone la confirmación absoluta de reservas minerales rentables.

## 12. Próxima Fase Recomendada

**Fase 6 — Evolución del Modelo Geológico y Visual 3D**

Se recomienda cerrar la infraestructura de ingesta e iniciar una fase visual intensiva y comparativa:
- Separar drásticamente los modelos lógicos de *Anomalía de Densidad* frente a los de *Ley de Corte/Probabilidad Económica*.
- Refinar el renderizado Three.js (Sombras, ejes de profundidad paramétricos, transparencias geológicas y capas interactivas de confianza).
- Abordar visualmente las matrices de Incertidumbre (Uncertainty).
- Diseñar la experiencia UX para comparar en paralelo una Inversión Sintética (Demo) versus la Inversión validada desde CSV.
