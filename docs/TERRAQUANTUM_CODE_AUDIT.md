# TerraQuantum Code Audit

Fecha: 2026-05-08

Alcance: auditoria de lectura del backend, frontend, documentos y scripts `.bat` de TerraQuantum. No se modifico codigo productivo, no se refactorizo, no se corrigieron bugs y no se instalaron dependencias.

## 1. Resumen ejecutivo

### Que es TerraQuantum hoy

TerraQuantum es hoy una aplicacion de exploracion minera/geofisica con dos capas principales:

- Backend FastAPI que recibe datos gravimetricos, ejecuta una inversion 3D simplificada, genera modelos de bloques, persiste corridas por `project_id` y `run_id`, calcula reportes y expone endpoints de mina/escenarios.
- Frontend Next/React que permite importar CSV, previsualizar datos, lanzar inversion, cargar corridas, visualizar el modelo 3D, consultar datos/reportes y explorar vistas demo de mina, telemetria, IA y dashboards.

El producto ya tiene un flujo usable de extremo a extremo:

`CSV -> preview -> import/invert -> project_id/run_id -> block model -> setModel -> Scene3D -> HUD -> Datos`

Pero mezcla varias capas conceptuales: geofisica real, heuristicas economicas, demos de presentacion, estados visuales globales y reportes operacionales. Esa mezcla hace que algunas pantallas parezcan mas concluyentes de lo que realmente son.

### Que esta funcionando

- Importacion CSV con previsualizacion, validacion basica y resumen.
- Inversion gravimetrica desde CSV hacia un modelo volumetrico.
- Persistencia de corridas por proyecto/run en `terraquantum-backend/data/projects/...`.
- Carga de modelos de bloque desde backend hacia frontend.
- Render 3D interactivo de celdas/bloques con filtros visuales, slices y HUD.
- Listado y detalle de corridas guardadas.
- Comparacion/exportacion de corridas en endpoints backend.
- Flujo conceptual de diseno minero y escenarios.
- Estado global Zustand suficiente para compartir modelo, reporte, objetivo, voxel, filtros y controles.

### Que esta desordenado

- No existe un concepto central de `activeRun` en frontend. Muchas vistas dependen de props, estados locales o inferencias.
- `DatosView` concentra demasiadas responsabilidades: historial de proyectos, diagnosticos, comparacion, sweep, reporte, economia demo y detalles de corrida.
- `Scene3D` hace render, filtros, seleccion, envolvente, controles visuales y parte de la semantica de exploracion.
- El modo presentacion/demo esta montado de forma global y contamina el flujo real.
- La metadata de importacion CSV existe en backend pero no esta tratada como entidad principal en Datos.
- Hay endpoints y servicios legacy que escriben/leen `data/block_model_001.parquet`, coexistiendo con el sistema nuevo de project/run.
- Algunos controles globales existen pero su efecto real no siempre se ve en la escena.
- Algunos scripts `.bat` tienen rutas duras o inconsistentes.

### Que es real

- La aplicacion realmente procesa CSV gravimetrico.
- El backend realmente ejecuta una inversion numerica simplificada.
- El backend realmente persiste archivos por proyecto/run.
- El frontend realmente transforma y renderiza un modelo 3D recibido desde backend.
- Los endpoints de listado, detalle, comparacion y exportacion de corridas existen.
- El flujo CSV a modelo 3D esta conectado.

### Que es demo

- La interpretacion de `probability`, `grade` y `avg_grade` es heuristica, no una estimacion geologica/economica auditada.
- La envolvente 3D es una ayuda visual derivada de celdas top-score, no una superficie geologica validada.
- El diseno de mina es conceptual y mezcla algoritmos/heuristicas con datos derivados.
- La telemetria, MWD, FMS, satelite y varios paneles de dashboard tienen componentes simulados.
- El modo presentacion guia una narrativa comercial mas que una operacion geologica trazable.

## 2. Mapa backend

### Entrada, configuracion y almacenamiento

| Ruta | Proposito | Endpoints | Inputs | Outputs | Servicios llamados | Archivos leidos/escritos | Riesgos |
| --- | --- | --- | --- | --- | --- | --- | --- |
| `terraquantum-backend/main.py` | Punto de entrada FastAPI, CORS, registro de routers y endpoints base. | `/health`, `/system-status` y routers de API. | HTTP requests. | JSON de salud/estado y respuestas delegadas. | Routers bajo `api/`. | No aplica directo. | Si la configuracion CORS queda abierta para demo, puede ser riesgosa al pasar a produccion. |
| `terraquantum-backend/core/config.py` | Configuracion de paths, ambiente y constantes. | No aplica. | Variables/config local. | Paths y parametros compartidos. | Servicios backend. | Lee ambiente local si aplica. | Las rutas default pueden fijar comportamiento legacy si no se separa project/run. |
| `terraquantum-backend/core/store.py` | Capa de persistencia para proyectos/runs y archivos asociados. | No aplica directo. | `project_id`, `run_id`, payloads, dataframes. | Paths, estados de archivos, metadata. | APIs de runs, inversion, exportacion. | Escribe/lee bajo `data/projects/<project_id>/runs/<run_id>/`. | Es el nucleo de trazabilidad; si no se usa en todos los servicios aparecen divergencias con archivos legacy. |
| `terraquantum-backend/schemas/*.py` | Contratos Pydantic de requests/responses. | No aplica directo. | Payloads HTTP. | Modelos validados. | Routers y servicios. | No aplica. | Algunos nombres semanticos pueden sobredimensionar el significado cientifico de campos heurisiticos. |

### APIs principales

| Ruta | Proposito | Endpoints | Inputs | Outputs | Servicios llamados | Archivos leidos/escritos | Riesgos |
| --- | --- | --- | --- | --- | --- | --- | --- |
| `terraquantum-backend/api/project_runs.py` | Lista, carga, compara y exporta corridas persistidas. | `/project-runs`, `/project-run-detail`, `/compare-runs`, `/export-run`. | `project_id`, `run_id`, filtros/query params. | Listas de runs, detalle, comparacion, descarga/export. | `core.store`, serializers de reportes/modelos. | Lee `inputs.json`, `report.json`, `metrics.json`, `schedule.json`, parquet y metadata de run. | La UI no modela `activeRun`, por lo que el detalle cargado puede no ser la fuente unica de verdad. |
| `terraquantum-backend/api/gravity_import.py` | Previsualiza CSV y ejecuta inversion desde CSV importado. | `/gravity-import/preview`, `/gravity-import/invert`. | Archivo CSV, mapeo/parametros, `project_id`, `run_id`. | Preview, diagnosticos, resumen, modelo/reporte segun flujo. | Servicio de inversion geofisica, store. | Preview usa archivo temporal; invert guarda `source_gravity.csv`, `gravity_import_metadata.json`, parquets, reportes. | La metadata CSV queda poco visible en frontend; preview e importacion no son aun una entidad auditable central. |
| `terraquantum-backend/api/geophysics.py` | Inversion geofisica directa y sweep de sensibilidad. | `/geophysics-invert`, `/geophysics-sensitivity-sweep`. | Observaciones, parametros de inversion. | Modelo, diagnosticos, reportes/sweep. | `services.geophysics_service`, `exploration.gravimetry`. | Puede escribir modelos/reportes si recibe project/run. | Riesgo de presentar una inversion simplificada como modelo geofisico definitivo. |
| `terraquantum-backend/api/block_model.py` | Entrega el modelo de bloques al frontend en formato renderizable. | `/block-model`. | `project_id`, `run_id` o fallback legacy. | Celdas/bloques con coordenadas, score, densidad/probabilidad, metadata. | `services.block_model_service`, store. | Lee parquet de run o `data/block_model_001.parquet`. | Fallback legacy puede cargar un modelo que no corresponde a la corrida que el usuario cree ver. |
| `terraquantum-backend/api/generate.py` | Generacion de datos/modelo demo o sintetico. | `/generate`. | Parametros de generacion. | Modelo/reportes sinteticos. | `generate_deposit`, engine/servicios. | Puede escribir parquet/reportes. | Demo y real pueden mezclarse si no se etiqueta claramente. |
| `terraquantum-backend/api/scenario_sweep.py` | Lanza y consulta barridos de escenarios. | `/scenario-sweep`, `/scenario-progress/{jobId}`. | Parametros economicos/mineros. | Job id, progreso, resultados. | `scenario_sweep_service`, scheduler. | Lee modelo base, escribe resultados temporales/persistidos segun servicio. | Estado asincrono y resultados deben quedar asociados a run; hoy la trazabilidad no es central en UI. |
| `terraquantum-backend/api/mine_design.py` | Expone diseno minero conceptual. | Endpoints de diseno/pit segun router. | Parametros de pit/economia/modelo. | Pit, malla, metricas, cronograma. | `pit_design_service`, `fms`, `pit_mesh`. | Lee modelo de bloques; puede depender de fallback. | Si frontend no envia project/run, puede usar modelo legacy/default. |

### Servicios y motores

| Ruta | Proposito | Endpoints | Inputs | Outputs | Servicios llamados | Archivos leidos/escritos | Riesgos |
| --- | --- | --- | --- | --- | --- | --- | --- |
| `terraquantum-backend/services/geophysics_service.py` | Orquesta la inversion, normaliza observaciones, genera reportes y persiste resultados. | No aplica directo. | Observaciones gravimetricas, parametros de grilla/inversion, project/run. | Dataframes de modelo, anomalias, reporte, diagnosticos. | `exploration.gravimetry`, `core.store`. | Escribe `block_model.parquet`, `block_model_anomaly.parquet`, `observations.json`, `report.json`, `metrics.json`; puede copiar a `data/block_model_001.parquet`. | Copia legacy crea doble fuente de verdad. Campos como `probability`/`grade` son heuristicas. |
| `terraquantum-backend/services/block_model_service.py` | Convierte parquet/backend a payload frontend. | No aplica directo. | Path de modelo o project/run. | Lista de celdas con coordenadas y atributos. | `core.store`, lectura parquet. | Lee parquet de run o legacy. | Transformacion de profundidad `y` a coordenada Three.js puede inducir confusion si no se documenta en UI. |
| `terraquantum-backend/exploration/gravimetry.py` | Implementa inversion gravimetrica simplificada, kernels, grillas y scoring. | No aplica. | Observaciones x/y/z/anomaly, parametros fisicos. | Modelo 3D, residuales, score/probabilidad. | Algebra numerica/LSQR. | No escribe directo salvo por servicio llamador. | Matematica real pero simplificada; densidad/probabilidad no equivale a mineralizacion validada. |
| `terraquantum-backend/engine.py` | Motor legacy de targeting/deposito. | No aplica directo. | Parametros/modelo. | Objetivos, block model legacy. | `TargetingEngine`, utilidades. | Escribe/lee `data/block_model_001.parquet`. | Legacy activo puede contaminar flujos nuevos. |
| `terraquantum-backend/pit_design_service.py` | Diseno conceptual de pit y metricas economicas. | No aplica directo. | Modelo de bloques, parametros economicos/mineros. | Pit shells, metricas, bloques seleccionados. | `fms`, `pit_mesh`. | Lee modelo base; escribe resultados segun API. | Usa grade/profit heuristico; no es estudio minero operativo. |
| `terraquantum-backend/fms.py` | Algoritmo/heuristica de flujo o seleccion para mina. | No aplica. | Bloques, pesos, restricciones. | Seleccion/solucion de pit. | Pit design. | No aplica directo. | Validacion tecnica pendiente antes de llamar esto optimo minero. |
| `terraquantum-backend/pit_mesh.py` | Construccion de malla 3D de pit. | No aplica. | Bloques/pit shell. | Geometria renderizable. | Pit design. | No aplica directo. | La malla puede parecer una geometria ingenieril validada sin serlo. |
| `terraquantum-backend/scenario_sweep_service.py` | Ejecuta barridos de sensibilidad/escenarios. | No aplica directo. | Parametros de escenario. | Resultados comparables. | Scheduler, pit/geophysics segun caso. | Puede leer/escribir resultados. | Falta anclar resultados claramente a `activeRun`. |
| `terraquantum-backend/scheduler.py` | Manejo de jobs/progreso. | No aplica directo. | Job id, funcion, parametros. | Estado/progreso. | Servicios de sweep. | Estado en memoria/temporal. | Si el backend reinicia, se puede perder estado si no hay persistencia robusta. |
| `terraquantum-backend/generate_deposit.py` | Genera deposito/modelo sintetico. | No aplica directo. | Parametros demo. | Modelo sintetico. | Engine/utilidades. | Escribe datos demo si se invoca. | Debe estar claramente separado de corridas reales. |

### Scripts y documentos auxiliares

| Ruta | Proposito | Endpoints | Inputs | Outputs | Servicios llamados | Archivos leidos/escritos | Riesgos |
| --- | --- | --- | --- | --- | --- | --- | --- |
| `*.bat` en raiz/backend/web | Arranque o automatizacion local. | No aplica. | Paths locales, comandos. | Servidores o comandos ejecutados. | Backend/frontend. | No deberian escribir codigo. | Hay rutas duras/inconsistentes; pueden fallar o arrancar contexto equivocado. |
| `docs/*.md` | Historial de decisiones, formatos CSV y auditorias previas. | No aplica. | Lectura humana. | Especificaciones y deuda conocida. | No aplica. | No aplica. | Parte de la verdad del proyecto esta en docs, parte en codigo. Falta consolidacion. |

## 3. Mapa frontend

### App, estado y cliente API

| Ruta | Proposito | Estado usado | APIs llamadas | Datos mostrados | Riesgos |
| --- | --- | --- | --- | --- | --- |
| `terraquantum-web/src/app/page.tsx` | Composicion principal de la aplicacion y vistas. | Estado global de vista, modelo, reporte y controles; estados locales de modo/paneles. | Indirectas via componentes. | Vista activa, layout, paneles globales. | Monta modo presentacion/demo global; no hay `activeRun` central. |
| `terraquantum-web/src/store/useAppStore.ts` | Zustand global. | `model`, `report`, `bestTarget`, `bestVoxel`, `pitModelUrl`, controles visuales, slices, seleccion, vistas. | No llama directo. | Fuente compartida de UI/modelo. | Estado global mezcla datos reales, controles visuales y demo; falta entidad `activeRun`. |
| `terraquantum-web/src/lib/frontendApi.ts` | Cliente fetch del backend/proxies. | No conserva estado. | Preview/import, block model, project runs, detail, compare, export, scenarios, mine design. | Respuestas normalizadas a componentes. | Bug probable en `exportRunUrl`: usa `runId` cuando el proxy/backend esperan `run_id`. |
| `terraquantum-web/src/app/api/**` | Proxies Next hacia backend. | No aplica salvo request. | Backend FastAPI. | JSON/descargas al frontend. | Si nombres de parametros divergen, la UI falla aunque backend funcione. |

### Vistas y componentes principales

| Ruta | Proposito | Estado usado | APIs llamadas | Datos mostrados | Riesgos |
| --- | --- | --- | --- | --- | --- |
| `terraquantum-web/src/components/Exploration3DView.tsx` | Contenedor de experiencia 3D, HUD y controles asociados. | `model`, `report`, `bestTarget`, `bestVoxel`, controles de vista. | Carga modelo via helpers/API segun flujo. | Escena 3D, resumen, objetivo, HUD. | Une render, narrativa y datos de exploracion; puede presentar demo y real juntos. |
| `terraquantum-web/src/components/GravityCsvPreviewPanel.tsx` | Selecciona CSV, ejecuta preview, import/invert y carga modelo. | Estado local de archivo, preview, loading, resumen; actualiza Zustand con modelo/reporte. | `/gravity-import/preview`, `/gravity-import/invert`, `/block-model` o helpers equivalentes. | Preview CSV, diagnosticos, resumen de inversion. | Tiene demasiadas responsabilidades; metadata CSV no queda como entidad persistente visible en Datos. |
| `terraquantum-web/src/components/Scene3D.tsx` | Render principal Three.js del modelo. | `model`, seleccion, filtros, slices, controles visuales, best voxel/target. | No deberia llamar APIs directamente. | Celdas/bloques, envolvente, objetivo, slices, labels/HUD. | Archivo grande; la envolvente puede parecer geologia real; algunos controles globales tienen efecto incierto. |
| `terraquantum-web/src/components/DatosView.tsx` | Vista de datos, historial, reportes, diagnosticos, comparaciones y economia. | `model`, `report`, estados locales de runs, comparacion, sweep, tabs. | Project runs, run detail, compare, export, scenario sweep. | Runs, metricas, archivos, reportes, diagnosticos y tablas. | Demasiado grande y mezclado; omite metadata CSV como elemento principal; mezcla real, demo, economia y diagnostico. |
| `terraquantum-web/src/components/MineDesignView.tsx` | UI de diseno minero conceptual. | Modelo/reporte y parametros locales. | Endpoints de mine design. | Pit, metricas, parametros. | Si no pasa project/run, puede operar sobre modelo legacy/default. |
| `terraquantum-web/src/components/MineDesign3D.tsx` | Render de pit/diseno minero. | Pit/modelo generado, controles 3D. | Indirectas via MineDesignView. | Pit, bloques mineros, geometria. | Puede parecer diseno de ingenieria definitivo aunque el origen sea heuristico. |
| `terraquantum-web/src/components/PitMetricsPanel.tsx` | Panel de metricas de pit. | Metricas de pit. | No directo. | Tonelaje, valor, ratios/metricas. | Depende de calidad semantica del modelo y parametros. |
| `terraquantum-web/src/components/TelemetryConsole.tsx` | Consola de telemetria/demo operacional. | Estado local `inputMode` y datos demo. | Puede usar endpoints o simulacion segun modo. | Telemetria, observaciones, estados. | Demo operacional mezclado con app de exploracion. |
| `terraquantum-web/src/components/GeoDashboard.tsx` | Dashboard geologico/visual. | Modelo, leyenda, controles. | No directo o indirecto. | Resumen visual y leyenda. | `showLegend` parece tener efecto principalmente aqui, no en todo el 3D. |
| `terraquantum-web/src/components/DemoGuidePanel.tsx` | Modo presentacion y narrativa guiada. | Estado local de paso/modo. | No central. | Guia, highlights, narrativa. | Debe eliminarse primero: contamina percepcion del producto real. |
| `terraquantum-web/src/components/BackendStatusBadge.tsx` | Estado de conexion con backend. | Estado local de health. | `/health` o `/system-status`. | Badge de backend. | Correcto para dev, pero no reemplaza trazabilidad de corrida. |
| `terraquantum-web/src/components/HomeView.tsx` | Inicio/landing interna. | Estado de navegacion. | Indirectas. | Accesos y contenido inicial. | Puede reforzar narrativa demo si no prioriza flujo operativo. |
| `terraquantum-web/src/components/MapeoIAView.tsx` | Vista de IA/mapeo conceptual. | Estados locales/demo. | Segun implementacion. | Mapas, predicciones o texto IA. | Riesgo de mezclar prediccion demo con datos importados. |
| `terraquantum-web/src/components/NavBar.tsx` | Navegacion principal. | Vista activa. | No directo. | Tabs/rutas visuales. | Debe reflejar una arquitectura por run, no solo vistas sueltas. |
| `terraquantum-web/src/components/WelcomeScreen.tsx` | Pantalla de bienvenida. | Estado local/global de inicio. | No directo. | Mensaje inicial y CTAs. | Si se mantiene, debe conducir al flujo real CSV/project/run. |
| `terraquantum-web/src/components/BottomControls.tsx` | Controles inferiores de visualizacion. | Visual controls, slices, toggles. | No directo. | Botones/toggles/sliders. | Algunos controles como `showMineDesign`/`gestureMode` parecen no tener efecto completo en `Scene3D`. |

## 4. Flujo CSV completo

### CSV -> preview

1. El usuario selecciona un CSV en `GravityCsvPreviewPanel`.
2. El frontend envia el archivo al endpoint/proxy de preview.
3. Backend recibe el archivo en `/gravity-import/preview`.
4. Backend lee una muestra del CSV, detecta columnas, valida formato y devuelve resumen/diagnosticos.
5. Frontend muestra preview, columnas, problemas y habilita importacion si el archivo es aceptable.

### preview -> import

1. El usuario confirma importacion/inversion.
2. `GravityCsvPreviewPanel` vuelve a enviar el CSV completo con parametros y, si existen, `project_id`/`run_id`.
3. Backend entra por `/gravity-import/invert`.
4. Backend normaliza observaciones y metadata de importacion.
5. Backend guarda el CSV original como `source_gravity.csv` cuando hay run persistido.
6. Backend guarda `gravity_import_metadata.json` con informacion de importacion.

### import -> invert

1. `gravity_import` llama al servicio geofisico.
2. `geophysics_service` prepara observaciones y parametros.
3. `exploration/gravimetry.py` ejecuta la inversion en grilla 3D.
4. Se calculan densidades/anomalias/residuales y scores heurisiticos.
5. Se generan `block_model.parquet`, `block_model_anomaly.parquet`, `report.json`, `metrics.json` y `observations.json`.

### invert -> project_id/run_id

1. Si el request trae `project_id` y `run_id`, el backend escribe bajo:
   `terraquantum-backend/data/projects/<project_id>/runs/<run_id>/`
2. Esa carpeta se transforma en la unidad real de trazabilidad.
3. Si no hay project/run o si se usa flujo legacy, puede aparecer/actualizarse `data/block_model_001.parquet`.

### project_id/run_id -> block model

1. Frontend pide el modelo a `/block-model` usando project/run.
2. Backend ubica el parquet del run.
3. `block_model_service` convierte filas del modelo en celdas renderizables.
4. Se transforma la profundidad/eje vertical para Three.js: el backend maneja profundidad positiva hacia abajo y el frontend/servicio la convierte a coordenadas de escena.

### block model -> setModel

1. Frontend recibe las celdas.
2. Normaliza nombres/campos si hace falta.
3. Llama a `setModel` en Zustand.
4. Tambien actualiza `report`, `bestTarget` o `bestVoxel` cuando el payload los trae o cuando se derivan en UI.

### setModel -> Scene3D

1. `Scene3D` consume `model` desde Zustand/props.
2. Construye instancias 3D de bloques/celdas.
3. Aplica filtros visuales, scoring, slices y colores.
4. Deriva highlights como mejor voxel/objetivo.

### Scene3D -> HUD -> Datos

1. El HUD muestra resumen del modelo visible, target, scores y/o metricas clave.
2. `DatosView` muestra reportes, historial de runs, diagnosticos y comparaciones.
3. El problema actual: Datos no es aun la fuente clara de metadata CSV y trazabilidad; parte de la informacion queda en preview/import, parte en run detail y parte en estado global.

## 5. Flujo project/run

### Donde se guarda

La unidad persistente es:

`terraquantum-backend/data/projects/<project_id>/runs/<run_id>/`

Archivos esperados o encontrados por run:

- `block_model.parquet`
- `block_model_anomaly.parquet`
- `inputs.json`
- `observations.json`
- `report.json`
- `metrics.json`
- `schedule.json`
- `source_gravity.csv`
- `gravity_import_metadata.json`

### Como se lista

- Frontend llama a cliente/proxy de project runs.
- Backend responde desde `/project-runs`.
- `core.store` recorre proyectos/runs y arma resumen.
- `DatosView` muestra historial/lista.

### Como se carga

- Frontend solicita `/project-run-detail` con `project_id` y `run_id`.
- Backend devuelve archivos disponibles, resumen, metricas, reporte y metadata.
- Para ver 3D se solicita `/block-model` con el mismo project/run.
- Frontend actualiza `model` y `report`.

### Como se exporta

- Backend expone `/export-run`.
- La intencion es exportar paquete o archivo asociado al run.
- Riesgo detectado: el helper frontend `exportRunUrl(projectId, runId)` parece construir `runId` en query string, mientras el proxy/backend esperan `run_id`. Eso puede romper la descarga desde UI aunque pruebas manuales al endpoint correcto funcionen.

### Que falta

- Un `activeRun` global en Zustand con `projectId`, `runId`, estado de archivos, metadata CSV, origen del modelo y timestamps.
- Que todas las vistas lean/escriban contexto desde `activeRun`.
- Que Datos muestre `source_gravity.csv` y `gravity_import_metadata.json` como parte central de la trazabilidad.
- Que mine design, scenario sweep y export usen explicitamente el mismo active run.
- Que no exista fallback silencioso a `data/block_model_001.parquet` cuando el usuario cree estar en una corrida especifica.

## 6. Flujo modelo 3D

### Que devuelve backend

El backend devuelve una coleccion de celdas/bloques con coordenadas, dimensiones y atributos derivados del modelo:

- Centro o posicion espacial.
- Tamano de celda/bloque.
- Densidad o anomalia estimada.
- Score/probability heuristico.
- Campos derivados como grade/avg_grade cuando aplica.
- Metadata/resumen del modelo y corrida.

El origen correcto deberia ser el parquet del run activo. El fallback legacy es `data/block_model_001.parquet`.

### Que transforma frontend

El frontend:

- Convierte la respuesta en el tipo de celda esperado por `Scene3D`.
- Guarda el modelo con `setModel`.
- Actualiza reporte/objetivo si viene disponible.
- Aplica filtros visuales por score/probabilidad/densidad.
- Aplica controles de slice y visualizacion.

### Que renderiza Scene3D

`Scene3D` renderiza:

- Bloques/celdas como instancias 3D.
- Colores segun score, densidad, probabilidad u otra metrica visual.
- Seleccion de voxel/celda.
- Mejor target o best voxel.
- Slices por ejes.
- Envolvente visual alrededor de zonas destacadas.
- Elementos auxiliares de camara, luces, labels/HUD segun configuracion.

### Que representa la envolvente

La envolvente representa una ayuda visual calculada a partir de las celdas destacadas/top-score. En la practica funciona como una forma suavizada o volumen alrededor del bounding box/zona de mayor interes.

No representa necesariamente:

- Un cuerpo mineral real.
- Una isosuperficie geofisica validada.
- Una envolvente geologica interpretada por un geologo.
- Un limite de mena o pit economico.

### Que esta mal o puede inducir a error

- La envolvente parece mas cientifica de lo que es.
- La palabra `probability` puede sugerir probabilidad mineral real, pero deriva de scoring/residuales.
- `grade`/`avg_grade` pueden parecer ley minera real aunque son heuristicas.
- El eje vertical/profundidad necesita rotulacion clara para evitar confundir y positivo abajo con coordenadas Three.js.
- Los colores pueden inducir interpretacion geologica si no se separan modos: densidad, residual, score, target, demo.
- La escena mezcla render de exploracion, controles demo y potencialmente diseno minero.

## 7. Flujo Datos

### Que muestra DatosView

`DatosView` muestra o concentra:

- Historial/listado de project runs.
- Detalle de run.
- Archivos disponibles.
- Reportes y metricas.
- Diagnosticos de inversion.
- Comparacion entre runs.
- Exportacion.
- Scenario sweep/progreso.
- Secciones de economia o mina conceptual.
- Estados de carga/error.

### Que deberia mostrar

Datos deberia ser la vista de trazabilidad y evidencia:

- Run activo.
- Proyecto activo.
- CSV original y metadata de importacion.
- Columnas detectadas y mapeadas.
- Observaciones usadas.
- Parametros de inversion.
- Archivos generados.
- Reporte tecnico.
- Metricas de ajuste/residuales.
- Version/origen del modelo 3D cargado.
- Comparaciones entre runs con criterios explicitos.

### Que esta mezclado

- Trazabilidad de CSV.
- Diagnostico geofisico.
- Reporte de corrida.
- Comparacion de runs.
- Economia conceptual.
- Mina/demo.
- Sweep asincrono.
- Estados de UI y narrativa.

### Que deberia separarse

- `RunDataPanel`: datos crudos, CSV, metadata, archivos.
- `InversionDiagnosticsPanel`: ajuste, residual, parametros, advertencias.
- `RunReportPanel`: resumen tecnico de la corrida.
- `RunComparisonPanel`: comparacion entre runs.
- `ScenarioSweepPanel`: barridos/escenarios asociados al run.
- `EconomicDemoPanel` o moverlo fuera de Datos si sigue siendo demo.

## 8. Estado global Zustand

### Estados importantes y problemas

| Estado | Uso actual | Problema |
| --- | --- | --- |
| `model` | Modelo 3D cargado/renderizado. | No esta ligado formalmente a `project_id/run_id`; puede quedar desincronizado con Datos. |
| `report` | Reporte asociado a inversion/modelo. | Puede provenir de run, import o flujo legacy sin origen explicito. |
| `bestTarget` | Objetivo destacado para HUD/3D. | Puede parecer interpretacion geologica final; deberia tener fuente y criterio. |
| `bestVoxel` | Celda/voxel destacado o seleccionado. | Mezcla seleccion visual, scoring y narrativa de target. |
| `pitModelUrl` | Referencia a modelo/pit de mina. | Debe asociarse a run y parametros de mina; hoy puede quedar suelto. |
| Visual controls | Colores, leyenda, filtros, modos de visualizacion. | Algunos controles parecen tener alcance parcial o efecto no evidente. |
| Slice controls | Cortes por ejes/profundidad. | Deben estar claramente separados de filtros de datos reales. |
| `showMineDesign` | Toggle relacionado con mina. | Efecto incierto si Scene3D no lo consume completamente. |
| `gestureMode` | Control de interaccion. | Puede estar definido globalmente sin impacto consistente. |
| Presentation mode | Modo demo/presentacion. | Existe principalmente como estado local/componente demo, no como dominio real; debe eliminarse primero. |
| Demo states | Telemetria, satelite, MWD/FMS, guia demo. | Mezclan storytelling con operacion real; deben aislarse o removerse. |

### Estado que falta

Debe existir un `activeRun` global, por ejemplo:

```ts
activeRun: {
  projectId: string
  runId: string
  source: "csv" | "synthetic" | "legacy"
  files: RunFiles
  csvMetadata?: GravityImportMetadata
  loadedModelAt?: string
}
```

Este estado deberia ser la fuente unica para:

- Cargar modelo.
- Mostrar Datos.
- Exportar run.
- Comparar runs.
- Lanzar diseno minero.
- Lanzar scenario sweep.
- Mostrar HUD con origen trazable.

## 9. Riesgos actuales

### Arquitectura

- Falta `activeRun` como eje de aplicacion.
- Backend nuevo por project/run convive con fallback legacy.
- Componentes grandes concentran demasiadas responsabilidades.
- Proxies frontend y endpoints backend pueden divergir en nombres de parametros.
- Demo y real no estan separados por capa.

### Fisica y geociencia

- La inversion gravimetrica es simplificada y necesita auditoria tecnica antes de decisiones reales.
- `probability` no debe interpretarse como probabilidad geologica calibrada.
- `grade`/`avg_grade` no deben interpretarse como ley minera real sin modelo geoestadistico.
- La envolvente 3D no es una interpretacion geologica validada.
- Falta trazabilidad visible entre observaciones, parametros, residual y modelo final.

### UI

- Modo presentacion contamina la interfaz operacional.
- Datos mezcla demasiadas capas.
- Scene3D puede inducir a sobreinterpretar colores, envolvente y targets.
- Algunos controles parecen existir sin efecto completo.
- La descarga/exportacion puede fallar por query param incorrecto.

### Trazabilidad

- Metadata CSV existe pero no esta al centro de Datos.
- No se ve claramente que modelo esta cargado y de que run viene.
- No todos los flujos downstream reciben project/run explicitamente.
- Fallback legacy puede ocultar errores de seleccion de corrida.

### Deuda tecnica

- `DatosView` es demasiado grande.
- `Scene3D` es demasiado grande.
- `GravityCsvPreviewPanel` mezcla preview, inversion, persistencia y carga visual.
- Scripts `.bat` con rutas fragiles.
- Tipos y contratos frontend/backend necesitan consolidacion.

### Archivos demasiado grandes

- `DatosView.tsx`: candidato principal a refactor por responsabilidad y tamano.
- `Scene3D.tsx`: candidato a separar render, seleccion, envolvente, slices y HUD.
- `GravityCsvPreviewPanel.tsx`: candidato a separar uploader, preview, inversion y resumen.

## 10. Recomendaciones priorizadas

Orden exacto recomendado:

1. eliminar modo presentacion
2. activeRun
3. mover metadata CSV a Datos
4. limpiar Figura 3D
5. auditar modelo geofisico
6. refactor DatosView
7. escena 3D geologica seria

### 1. eliminar modo presentacion

Remover el modo presentacion como capa global antes de seguir desarrollando. Esto reduce ruido conceptual y evita que la UI mezcle narrativa demo con flujo real.

### 2. activeRun

Crear una entidad global `activeRun` y hacer que modelo, reporte, exportacion, comparacion, Datos, mina y sweep dependan de ella. Este es el cambio arquitectonico mas importante.

### 3. mover metadata CSV a Datos

Convertir `source_gravity.csv` y `gravity_import_metadata.json` en informacion visible y central dentro de Datos. La pregunta "de donde viene este modelo" debe responderse en una sola pantalla.

### 4. limpiar Figura 3D

Separar visualizacion de interpretacion. La escena debe mostrar modos claros: densidad, residual, score, target y demo si existiera. La envolvente debe rotularse como visual aid si se mantiene.

### 5. auditar modelo geofisico

Auditar con criterio tecnico la inversion, unidades, kernel, regularizacion, residual, scoring y nombres de campos. Renombrar campos que puedan inducir a error.

### 6. refactor DatosView

Separar Datos en paneles especializados. No cambiar comportamiento primero; solo aislar responsabilidades despues de tener `activeRun` y metadata CSV.

### 7. escena 3D geologica seria

Redisenar `Scene3D` como una herramienta geologica seria: ejes/leyendas/unidades, modos de capa, cortes geologicos, incertidumbre, referencias de observaciones y separacion total de demos.

## Cierre

TerraQuantum ya tiene un flujo tecnico real de CSV a inversion y visualizacion 3D. El principal problema no es que falten piezas, sino que las piezas reales, heuristicas y demo estan superpuestas. La siguiente fase deberia ordenar el producto alrededor de una corrida activa trazable, hacer visible la evidencia CSV/modelo en Datos y bajar la carga narrativa de la escena 3D.
