# TerraQuantum System Audit (V1)

**Fecha:** 2026-05-09
**Alcance:** Auditoría completa de lectura del código fuente (frontend y backend) de TerraQuantum. El objetivo de este documento es establecer una base industrial ordenada, identificando la arquitectura real, la deuda técnica, y las áreas donde las simulaciones o flujos "demo" interfieren con la trazabilidad científica. No se ha modificado código productivo.

---

## 1. Resumen Ejecutivo

### Qué es TerraQuantum hoy
TerraQuantum es una plataforma de exploración minera/geofísica que transforma datos físicos (gravimetría) en un modelo 3D preliminar de densidad y contraste de anomalías. Actualmente funciona como un prototipo avanzado que integra ingesta de datos, inversión geofísica 3D simplificada, diseño de rajo (pit design) conceptual y evaluación económica/operacional (FMS) en un único flujo visual.

### Qué funciona
- La importación y validación de archivos CSV con observaciones gravimétricas reales.
- El motor de inversión geofísica (backend) que genera un Block Model (en Parquet) a partir de los datos.
- La persistencia estructurada de datos bajo la convención `project_id`/`run_id` en el disco local (`core/store.py`).
- El renderizado 3D de modelos de bloques usando `@react-three/fiber` en el frontend, con filtros visuales aplicables en tiempo real.
- Las integraciones a través de endpoints FastAPI proxy-eadas por Next.js.

### Qué está desordenado
- **Falta de un `activeRun` central:** El estado global (`useAppStore`) no mantiene una trazabilidad estricta de qué corrida (`project_id`/`run_id`) se está visualizando en cada momento, lo que provoca que módulos como "Diseño Mina" puedan usar archivos por defecto (ej. `block_model_001.parquet`) sin saberlo.
- **Sobrecarga de Componentes:** Componentes como `DatosView` y `Scene3D` mezclan visualización de datos, lógicas comerciales, y dashboards simulados en un solo lugar.
- **Intersección Demo vs Real:** Existen componentes (`DemoGuidePanel`, visuales de telemetría MWD) que fuerzan comportamientos determinísticos y simulados, mezclándose con flujos de datos reales importados por el usuario.

### Qué es real
- El pipeline de lectura de CSV y parsing espacial en el frontend y backend.
- La matemática base de inversión geofísica (`exploration/gravimetry.py` usa `scipy.sparse.linalg.lsqr`).
- La serialización/deserialización de Block Models en formato Parquet.
- El motor Lerchs-Grossmann (LG) basado en algoritmos de flujo máximo (Max-Flow/Min-Cut con `PyMaxflow`) en el backend para diseño de pit.

### Qué es demo / heurístico
- **Terminología Geológica:** Campos como `probability`, `grade`, o `target_score` son *heurísticas numéricas* derivadas del contraste de densidad, **no son variables de estimación geoestadística ni validan mineralización real**.
- **Flujo MWD / FMS:** Las simulaciones de perforación (MWD) y las temperaturas/status de camiones en el FMS son componentes puramente visuales y determinísticos, sin conexión a sensores reales.
- **AnomalyEnvelope:** Es un cascarón visual en React (basado en un bounding box) y no una isosuperficie calculada matemáticamente en el backend.

### Riesgo Principal Actual
La mezcla de términos científicos reales con simulaciones comerciales. Si un usuario industrial ingresa datos CSV reales, el sistema podría responderle con leyes mineras (`grade`) inventadas o envolventes ("Mineral Complex") no validadas, poniendo en duda la credibilidad matemática del producto. La trazabilidad se rompe en la interfaz gráfica.

---

## 2. Arquitectura Actual Real

La plataforma opera en una arquitectura desacoplada de 3 niveles:

1. **Frontend (React / Next.js):**
   - **Renderizado 3D:** `@react-three/fiber` y `@react-three/drei`.
   - **Estado:** `Zustand` (`store/useAppStore.ts`).
   - Maneja la UI de importación, las cámaras, luces y filtros sobre los datos (voxels).
2. **App/API Proxy Layer (Next.js):**
   - Rutas en `app/api/*` que actúan de puente para evitar problemas de CORS, inyectando URLs al backend FastAPI (usualmente apuntando al puerto `8010`).
3. **Backend (FastAPI - Python):**
   - **Endpoints REST:** En `terraquantum-backend/api/`.
   - **Project/Run Storage:** Capa local en `core/store.py` que lee y escribe Parquet y JSON en `data/projects/`.
   - **Compute / Geophysics Engine:** Servicios numéricos basados en `numpy`, `scipy` (`exploration/gravimetry.py`).
   - **Mine Design Engine:** `services/pit_design_service.py` y `engine.py` (Lerchs-Grossmann optimization).
   - **FMS/Scheduler:** `fms.py` y `scheduler.py` (rutinas estocásticas / heurísticas para simulaciones de despachos y sweep).

---

## 3. Mapa Backend Archivo por Archivo

| Ruta | Propósito | Entradas / Salidas | Servicios | Lectura/Escritura | Estado |
| :--- | :--- | :--- | :--- | :--- | :--- |
| `main.py` | Entrada de FastAPI, registro de rutas. | REST HTTP -> Router JSON. | APIs | Ninguno. | Real |
| `api/gravity_import_api.py` | Ingesta de CSV y preview. | CSV, params -> Preview JSON o Inversión | `geophysics_service`, `store` | `source_gravity.csv`, Parquets | Real |
| `core/store.py` / `block_model_store.py` | Trazabilidad y persistencia de datos. | IDs, Dataframes -> Paths, status | N/A | Lee/Escribe `data/projects/` | Real |
| `schemas/*` (ej. `geophysics_schema.py`) | Contratos Pydantic de la API. | JSON payload -> Objeto Py | N/A | Ninguno. | Real |
| `services/geophysics_service.py` | Orquesta validación, inversión y persistencia. | Observaciones -> Modelos, Reports | `gravimetry.py`, `store` | Parquets, JSONs de métricas | Real |
| `exploration/gravimetry.py` | Inversión matemática LSQR/Tikhonov. | Nubes de puntos -> Matrices 3D | SciPy sparse | En memoria | Real (Matemática base) |
| `engine.py` | Motor de targeting (MaxFlow) para LerchsGrossmann. | Parametros económicos -> Pit Shells | `PyMaxflow` | Archivos temporales | Mixto (Legado/Real) |
| `pit_mesh.py` | Construcción de mallas 3D trianguladas del Pit. | Bloques del Pit -> Geometría GLB | Trimesh, Shapely | Escribe `.glb` | Real |
| `scheduler.py` | Gestor simple de colas de trabajos (Sweep). | Jobs -> Status | `fms.py` | Temporales de barrido | Real |
| `services/pit_design_service.py` | Generación conceptual de mina (LOM, VNP). | Modelo bloques -> LOM Schedule | `engine.py`, `pit_mesh` | Lee Parquet activo | Mixto |
| `fms.py` | Simulación y despacho de camiones. | Variables económicas -> Asignaciones | `scheduler.py` | Memoria | Demo / Conceptual |

**Riesgo general del Backend:** Campos del modelo exportados como `probability` o `grade` son generados algorítmicamente sin correlación geoestadística dura.

---

## 4. Mapa Frontend Archivo por Archivo

| Ruta | Propósito | Estado Zustand (usa/modifica) | APIs que llama | Muestra | Estado |
| :--- | :--- | :--- | :--- | :--- | :--- |
| `app/page.tsx` | Contenedor global de UI. | `view`, controla vistas. | N/A | DemoGuidePanel, Nav | Mixto |
| `store/useAppStore.ts` | Estado Global. | `model`, `report`, controles visuales, estados FMS | N/A | N/A | Mixto (Desordenado) |
| `lib/terraquantum/frontendApi.ts` | Cliente fetch tipado. | N/A | Endpoints de backend via Next proxy | N/A | Real |
| `componentes/Scene3D.tsx` | Renderizador central Three.js. | `model`, `showVoxels`, slices, colores | N/A | InstancedMesh de datos, AnomalyEnvelope | Mixto (Render real + envolvente heurística) |
| `componentes/GravityCsvPreviewPanel.tsx` | Carga, valida y manda el CSV a inversión. | `setModel`, `setShow3D` | `/gravity-import/*` | Preview del archivo CSV, Inversión | Real |
| `componentes/DatosView.tsx` | Centraliza historiales, reports, sweeps. | `model`, `report` | `/project-runs/*`, `/compare-runs` | Metadatos y JSONs | Deuda técnica (gigante, mezclado) |
| `componentes/views/MineDesignView.tsx` | Pantalla de diseño de Pit. | `pitModelUrl`, parámetros eco | `/generate-pit` | PitMetricsPanel, MineDesign3D | Conceptual / Demo |
| `componentes/FmsDashboard.tsx` | Tablero de control de flota. | `fmsTrucks`, `lomMetrics` | N/A | Temperaturas, estatus | Demo |
| `componentes/huds/DemoGuidePanel.tsx` | Modal con narrativa guiada ("Pitch Mode"). | `setView` | N/A | Textos comerciales | Demo |

**Riesgo general del Frontend:** `GravityCsvPreviewPanel` inyecta modelos en Zustand pero no se registra globalmente un `activeRunId`. Esto significa que si luego vas a `MineDesignView`, la vista de mina no tiene una forma robusta de decir "dame el pit design para el runId X".

---

## 5. Flujo CSV Completo (Ingesta y Visualización)

Este es el pipeline crítico donde la trazabilidad a veces se quiebra:

1. **Usuario selecciona archivo:** En `GravityCsvPreviewPanel`.
2. **Validación:** Frontend envía a Next.js `/api/gravity-import/preview` → Backend `/gravity-import/preview`.
   - Backend lee, devuelve `import_metadata` con diagnósticos iniciales.
3. **Inversión:** El usuario presiona "Invertir". Se invoca frontend `/api/gravity-import/invert` → Backend `/gravity-import/invert`.
   - Se arma `GeophysicsInvertInput` que incluye observaciones (g), tamaño de grid, etc.
   - El backend **genera `project_id` y `run_id`**.
   - Invoca `run_geophysics_inversion()`. Guarda `source_gravity.csv`, genera Parquets y reportes en `data/projects/...`.
4. **Carga en Frontend:** `GravityCsvPreviewPanel` toma la respuesta y hace poll o solicita explícitamente `getExplorationBlockModelForRun`.
   - Se procesa el Parquet, backend envía array de celdas.
   - **[PUNTO DE QUIEBRE]** `GravityCsvPreviewPanel` llama a `setModel(data)` en Zustand. Sin embargo, no guarda un `activeRunId`. El frontend ahora tiene un modelo "suelto" en memoria.
5. **Renderizado (`Scene3D`):** El componente lee el `model` genérico y dibuja celdas.
6. **Revisión (`Datos`):** El usuario va a `DatosView` para ver el historial, pero como no hay `activeRunId` registrado, `DatosView` podría no saber cuál es la corrida actualmente renderizada sin heurísticas raras.

---

## 6. Flujo Geofísico Backend

1. **Ingreso:** Se lee la gravedad (`g`). Si la configuración original no es `m/s²`, el motor debe normalizar los datos, pero actualmente asume un esquema genérico. Convención estándar `Z` es altitud/profundidad, pero en Three.js `Y` es la vertical. El Backend hace esta conversión de ejes para entregar `y` como la cota visual al frontend.
2. **Grilla:** Se arma una matriz regular (`nx, ny, nz`) basada en las distancias interpoladas del área.
3. **Kernel & LSQR:** Se arma un kernel de sensibilidad inversamente proporcional al cuadrado de la distancia (con un `cutoff_radius`). Se usa `scipy.sparse.linalg.lsqr` minimizando un problema mal condicionado con un factor de suavizado espacial (Laplaciano) llamado `alpha_spatial` y regularización `lambda_mag`.
4. **Terminología Física vs Heurística:**
   - **Físico:** `density` (Densidad modelada invertida).
   - **Físico:** `anomaly_intensity` (Residual o contraste directo resultante de la ecuación matemática).
   - **Heurístico / Semántico:** `probability`, `target_score`. Estos valores se normalizan entre 0 y 1 para la UI, pero **no** representan una certeza estadística validada en campo.
   - **Legacy:** Cualquier mención a `grade` (ley de mineral) generada sin bloques de sondaje es puramente inventada.

---

## 7. Flujo Modelo 3D Frontend (`Scene3D`)

- **Instancing:** Usa `InstancedMesh` para dibujar miles de cubos o esferas de alta eficiencia.
- **`visualLayer`:** Un switch en Zustand que define qué campo de datos se mapea al color (`density`, `anomaly_intensity`, `target_score`).
- **Filtros y Slices:** Realiza operaciones puramente visuales `if (valor < corte) scale = 0`. Esto oculta celdas pero **no recalcula** recursos geológicos. Los recortes de X/Y/Z son shaders o condicionales visuales en el bucle `useFrame`.
- **`AnomalyEnvelope`:** Un truco visual. Calcula el Bounding Box del percentil más alto de valores anómalos y dibuja una esfera transparente achatada. **Riesgo:** Un geólogo pensará que es una isocara calculada.
- **Modelos flotando:** Ocurren porque las coordenadas locales (basadas en centros `cx, cy, cz`) no siempre se anclan correctamente sobre el plano Y=0 de la malla si el dominio vertical (`domainH`) no cuadra con la cota topográfica.

---

## 8. Flujo Datos (`DatosView.tsx`)

Actualmente es un gran "cajón de sastre" (80+ KB de archivo).
- **Muestra bien:** El listado histórico de corridas (Project Runs).
- **Muestra mezclado:** Metadatos de importación CSV, reportes de inversión técnica, corridas de FMS simuladas, gráficos de sweeps económicos, botones de exportación legacy.
- **Deuda Técnica:** Al intentar hacer todo (comparar runs, mostrar detalle, graficar), la mantención es casi imposible.
- **Propuesta:** Debe dividirse en pestañas y componentes atómicos: `<ProjectRunList />`, `<RunDiagnosticsPanel />`, `<RunEconomicPanel />`. Y debe ser controlado obligatoriamente por el `activeRun`.

---

## 9. Flujo Diseño Mina

1. **Payload:** Se envían los costos (mina, planta) y el precio del commodity desde la UI (`MineDesignView`).
2. **Archivo Fijo (Riesgo):** En `pit_design_schema.py`, vemos `file: str = "block_model_001.parquet"`. Si el frontend no especifica explícitamente `project_id`/`run_id` (y hoy no siempre lo hace por falta del activeRun), el Backend procesa silenciosamente un modelo genérico antiguo.
3. **Generación (`/generate-pit`):** Invoca el `pit_design_service`.
4. **LG Engine:** `engine.py` construye un grafo dirigido donde cada bloque minero es un nodo. Las aristas imponen ángulos de talud. `PyMaxflow` encuentra el corte de costo mínimo (pit óptimo).
5. **Scheduler:** Construye un LOM conceptual (Life of Mine) bajando bloque a bloque.
6. **Es Conceptual:** Asume que todo el bloque es 100% extraíble, que la ley inventada es real, y no considera recuperación metalúrgica compleja. Riesgo alto de sobrepromesa.

---

## 10. Flujo FMS (Gestión de Flota)

- **Datos:** Usa el LOM generado (tonelajes planificados) o asume métricas simuladas por defecto.
- **Determinístico:** En `FmsDashboard.tsx`, el estatus de los camiones, sus marcas y sus temperaturas están pre-calculadas en base al índice del camión o variaciones con `Math.sin()`.
- **Qué falta para ser industrial:** Una conexión a un protocolo en tiempo real (ej. MQTT), bases de datos de tiempos de ciclo (Cycle Times), demoras operacionales, y GPS tracking. Hoy, FMS en TerraQuantum es una interfaz 100% demo comercial.

---

## 11. Estado Global Zustand (`useAppStore.ts`)

### Estados mezclados
- `model`: Guarda el archivo genérico, pero no sabe su procedencia.
- `fmsTrucks`: Almacenado junto con física geológica.
- `mwdStatus`: Variables demo alojadas en el root.

### Propuesta Exacta de `activeRun`

Para que el proyecto sea industrial, se DEBE agregar esto a `useAppStore.ts`:

```typescript
// Nuevo estado conceptual a implementar:
interface ActiveRunState {
  activeProjectId: string | null;
  activeRunId: string | null;
  activeSource: "csv" | "synthetic" | "legacy" | null;
  
  // Referencias a los datos activos
  activeModel: BackendVoxelModel | null;
  activeReport: GeophysicsReport | null;
  activeImportMetadata: GravityImportMetadata | null;
  
  // Status de la corrida actual
  activeRunStatus: "idle" | "loading" | "error" | "ready";
}
```

---

## 12. Problemas Críticos Encontrados (Ordenados por Prioridad)

1. **Falta de `activeRun`:** Es imposible asegurar trazabilidad. Se corre el riesgo constante de estar viendo métricas del Run B en un modelo 3D del Run A.
2. **`pitDesignModel` consumiendo archivos fijos:** Si la UI falla al enviar el `run_id`, el backend responde usando `block_model_001.parquet`. Silencioso y mortal para la confianza de los datos.
3. **Demo Global / `DemoGuidePanel`:** Presente en la pantalla principal de una aplicación que requiere un look profesional, minando la legitimidad. Textos comerciales explícitos en código.
4. **`DatosView.tsx` gigante y colapsado:** Concentra 8 pantallas en un solo componente de frontend.
5. **Textos Engañosos:** Uso excesivo de la palabra "Mineral" o "Ley (Grade)" en el modelo geofísico. Una anomalía de densidad no asegura presencia de mineral económico.
6. **Envolvente (`AnomalyEnvelope`) engañosa:** Se dibuja como isocara pero es solo un volumen reactivo de React-Three-Fiber.

---

## 13. Plan de Rescate Industrial (Ruta de Trabajo)

Para pasar de Prototipo Avanzado a Base Industrial Ordenada sin tocar las dependencias productivas, la ruta debe ejecutarse de la siguiente manera:

### Fase 1.1 — Eliminar modo presentación / demo global
- **Objetivo:** Remover `DemoGuidePanel` y lógicas "Demo Fuerte" del estado.
- **Archivos Probables:** `useAppStore.ts`, `app/page.tsx`, `DemoGuidePanel.tsx`.
- **Criterio de Aceptación:** UI limpia sin botones flotantes de presentación comercial.

### Fase 1.2 — Crear `activeRun` conceptual en Zustand
- **Objetivo:** Implementar las variables de `ActiveRunState` en `useAppStore`.
- **Archivos Probables:** `useAppStore.ts`.
- **Riesgos:** Ninguno grave, añade campos inertes inicialmente.

### Fase 1.3 — Conectar CSV importado con `activeRun`
- **Objetivo:** Al retornar de `/gravity-import/invert`, guardar en Zustand el `project_id` y `run_id`.
- **Archivos Probables:** `GravityCsvPreviewPanel.tsx`, `useAppStore.ts`.

### Fase 1.4 — Mover metadata CSV a Datos
- **Objetivo:** En la pantalla "Datos", crear un sub-panel que dependa del `activeRun` y muestre cuántas filas del CSV fueron aceptadas.
- **Archivos Probables:** `DatosView.tsx`.

### Fase 1.5 — Limpiar Figura 3D
- **Objetivo:** Renombrar campos heurísticos visuales. Hacer explícito (con texto en UI) que `AnomalyEnvelope` es una aproximación y que la Gravedad no garantiza Mineral.
- **Archivos Probables:** `Scene3D.tsx`, `Exploration3DView.tsx`.

### Fase 1.6 — Hacer Diseño Mina dependiente de `activeRun`
- **Objetivo:** Obligar a que `MineDesignView` exija un `activeRunId` antes de ejecutar `/generate-pit`. Prohibir que consuma el fallback legacy.
- **Archivos Probables:** `MineDesignView.tsx`.

### Fase 1.7 — Refactor `DatosView`
- **Objetivo:** Dividir el monolito de 800 líneas en pestañas lógicas (Logs, CSV Info, Inversion Output, Economia).
- **Archivos Probables:** `DatosView.tsx` y creación de `componentes/views/datos/*`.

### Fase 1.8 — Auditoría geofísica de calidad del modelo
- **Objetivo:** (Solo revisión Backend) Validar variables en `geophysics_service.py` y renombrar variables de salida (`avg_grade` -> `estimated_anomaly_intensity`).
- **NO Tocar:** La matemática de Python. Sólo diccionarios de salida.

### Fase 1.9 — Escena 3D Geológica Seria
- **Objetivo:** Agregar Grid Helpers formales y ejes acotados en `Scene3D.tsx` que coincidan con las profundidades reales.
- **Archivos Probables:** `Scene3D.tsx`.

### Fase 1.10 — Reportes Industriales
- **Objetivo:** Permitir la descarga de un PDF / Parquet empaquetado exclusivamente asociado al `activeRunId`.
- **Archivos Probables:** `api/project_runs.py` (Backend), `DatosView` export button.

---

## 14. Recomendación Final

La **primera tarea de código** a realizar debe ser la **Fase 1.1 (Eliminar modo presentación) en conjunto con la Fase 1.2 (Crear activeRun en Zustand)**.
Remover el "ruido comercial" y sentar las bases de la trazabilidad en memoria es el cimiento para que cualquier refactorización subsiguiente (sobre `DatosView` o `MineDesignView`) tenga una fuente única de verdad garantizada y deje de depender de archivos o datos "por defecto" (legacy).
