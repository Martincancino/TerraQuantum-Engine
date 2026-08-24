# INFORME 08 — INGENIERÍA DE SOFTWARE Y ARQUITECTURA
## Cómo está construido TerraQuantum como sistema

**Destinatario:** ingeniería de software · arquitectura de sistemas · calidad de software científico
**Rama auditada:** `fases-19-25-cierre` · commit `c810ed5`
**Base de evidencia:** lectura directa de `main.py`, `core/*.py`, `api/*.py` (inventario), `terraquantum/__init__.py`, `services/run_queue_service.py`, `scripts/ci/generate_frontend_types.py`, `.github/workflows/ci.yml`, `requirements.txt`, y de la capa de frontend indicada.

> Autocontenido.

---

## 1. Forma general del sistema

Monorepo con dos mitades y separación estricta declarada:

```
terraquantum-backend/     Python · FastAPI · ~128.000 líneas
  exploration/            motores de física e inversión (núcleo científico)
  services/               orquestación, correcciones, ingesta, exportación (56 módulos)
  api/                    22 módulos de endpoints HTTP
  schemas/                contratos Pydantic (fuente de los tipos del frontend)
  core/                   config, errores, auth, métricas, observabilidad, licencia
  terraquantum/           paquete de scripting: API de usuario en Python
  middleware/             clave de API, Prometheus
  reporting/              generador de informes HTML
  tests/ · scripts/       suite y arneses de validación

terraquantum-web/         Next.js · React · TypeScript · Three.js · ~35.000 líneas
  componentes/ · lib/ · store/ · workers/ · e2e/
  src-tauri/              empaque de escritorio local-first
  types/backend-contracts.generated.ts   ← GENERADO, no escrito a mano
```

La **regla arquitectónica declarada** del proyecto es que toda la física y la matemática
viven en el backend, y que el frontend sólo visualiza y consume APIs. El informe 10
documenta tres lugares donde esa regla no se cumple del todo; el resto del sistema la
respeta.

---

## 2. La capa HTTP

### 2.1 Composición

`main.py` monta **22 routers** (`main.py:213-234`), cubriendo geofísica, modelo de bloques,
importación (v1 y v2), sondajes, multifísica, informes, proyectos, terreno, favorabilidad,
espectral, exportación, chat, correcciones, historial, realce magnético, estimación de
profundidad, licencia, diagnósticos, claves, métricas y sistema.

### 2.2 Middleware, con el orden razonado

```python
# Middleware order matters: last add_middleware = outermost layer.
# Stack: CORS (outer) → ApiKey → Prometheus (inner) → routes.
```
(`main.py:252-253`)

Que el orden esté **escrito** importa: en Starlette el último `add_middleware` queda más
externo, y es un detalle que se olvida y produce fallos sutiles (por ejemplo, métricas que
cuentan peticiones rechazadas por autenticación, o preflight CORS que no llega).

### 2.3 Una comprobación de seguridad que avisa en vez de romper

```python
if "*" in CORS_ORIGINS:
    # ADVERTENCIA DE SEGURIDAD: ... wildcard + credentials es rechazado por los
    # navegadores y señala una mala configuración.
```
(`main.py:84-90`)

Es la conducta correcta: la combinación comodín + credenciales viola la especificación CORS
y los navegadores la rechazan, de modo que fallaría *en el cliente* con un mensaje
incomprensible. Detectarlo en el arranque y nombrarlo ahorra horas.

---

## 3. El catálogo de errores

`core/errors.py` (763 líneas) define un catálogo de **63 especificaciones de error**
(`ErrorSpec`), cada una con:

- `code` — identificador estable (p. ej. `CSV_EMPTY`, `SOLVER_KERNEL_TOO_DENSE`);
- `severity` — error / advertencia / información;
- `user_message` — en español, con marcadores `str.format` rellenados con el contexto;
- `suggested_action` — **una acción concreta**.

La regla declarada es exigente (`core/errors.py:52-54`): todos los mensajes en español y de
más de 100 caracteres incluso tras rellenar los marcadores, y «cada uno propone una acción
concreta».

Sobre el catálogo se construye una jerarquía de excepciones tipadas —`CsvValidationError`,
`InsufficientDataError`, `SolverDivergenceError`, `SolverMemoryError`,
`ConflictingDataError`, `GeoreferencingError`— que **subclasean también las excepciones
estándar** correspondientes (`ValueError`, `MemoryError`) por compatibilidad con código que
ya las capturaba (`core/errors.py:711-733`).

**Valoración.** Un catálogo de errores con acción sugerida es lo que separa un prototipo de
un producto usable por alguien que no escribió el código. Aquí está bien hecho.

---

## 4. Configuración: inventariada, no dispersa

El backend expone **42 variables de entorno**, y hay un test de CI que las **censa por AST**
y falla si aparece una nueva sin declarar. Convierte la configuración en un inventario
auditable en lugar de un conjunto de `os.getenv` esparcidos.

### 4.1 Una lección de parseo, medida

`core/config.py:58-80` documenta un hallazgo que merece reproducirse porque es
instructivo. Las banderas booleanas se leían de dos formas incompatibles:

```python
os.getenv(X, "true").lower() != "false"     # USE_*, TQ_AUTH_ENABLED
os.getenv(X, "false").lower() == "true"     # OTEL_ENABLED
```

y ambas mienten fuera del par exacto `"true"`/`"false"`. Lo medido:

- `USE_BOUNDED_SOLVER=0` **no** hacía rollback: el solver seguía en TRF y el modelo salía
  byte-idéntico al defecto.
- `TQ_AUTH_ENABLED=` (vacío, lo que produce una línea `TQ_AUTH_ENABLED=` en `.env.local`)
  **activaba** la autenticación: `/geophysics/invert` pasaba de 404 a **401**. El camino
  principal se rompía por escribir una variable que se lee como «apagada».
- `OTEL_ENABLED=1` no encendía nada, por el defecto simétrico contrario.

La regla nueva es la correcta: valor vacío o ausente = el defecto declarado; vocabulario
conocido = lo que dice; **cualquier otra cosa mata el arranque nombrando la variable**.
«Un flag de seguridad no se adivina.»

### 4.2 Banderas que declaran su propio límite y su propio coste

Dos ejemplos que conviene destacar como práctica:

- `USE_BOUNDED_SOLVER` declara **hasta dónde llega**: «sólo decide por debajo de 8.000
  celdas activas. Por encima —el régimen normal del producto— el solver usa LSQR+clip esté
  como esté» (`core/config.py:219-221`).
- `USE_PROJECTED_SOLVER` declara **lo que cuesta apagarla**: el $\chi^2$ pasó de 0,244 a
  22,7, un factor 93. «Se deja la perilla —es la vía de escape si FISTA se rompe— pero
  queda escrito lo que cuesta usarla» (`core/config.py:226-232`).

---

## 5. El problema del contrato backend–frontend, y cómo se resolvió

### 5.1 El problema

El frontend declaraba a mano los tipos de las respuestas del backend, leyendo el código
Python. Nada garantizaba que siguieran coincidiendo: «el backend añade un campo y no falla
nada hasta que un usuario ve un dato vacío. Es la clase de bug que **no tiene test
posible** — porque el "test" sería volver a escribir el contrato a mano por tercera vez»
(`scripts/ci/generate_frontend_types.py:6-11`).

El diagnóstico es exacto: un contrato duplicado no se puede verificar duplicándolo otra vez.

### 5.2 La solución

`scripts/ci/generate_frontend_types.py` genera
`terraquantum-web/types/backend-contracts.generated.ts` (1.201 líneas) desde el esquema
OpenAPI que produce la propia aplicación, con un modo `--check` que **falla si hay deriva**.

### 5.3 Por qué no se usó la herramienta estándar

La justificación de no usar `openapi-typescript` está escrita y es defendible
(`scripts/ci/generate_frontend_types.py:13-20`):

1. añadir una dependencia de npm requiere permiso expreso en este repositorio;
2. el generador debe correr en el job de **backend** de la CI, donde vive la app que
   produce el esquema y donde **no hay Node**;
3. son 30 tipos desde un esquema ya en memoria: ~200 líneas de Python sin dependencias
   nuevas.

Es un ejemplo de decisión de dependencias tomada con criterio en lugar de por costumbre.

### 5.4 El hallazgo asociado

El trabajo que motivó esta pieza también corrigió algo más profundo: **44 de 65 rutas no
declaraban `response_model`**. Y declararlo no es gratis —un modelo estricto **borra**
campos no declarados, uno permisivo **inyecta** nulos—, de modo que la contramedida
adoptada fue `exclude_unset`. Es el tipo de detalle que decide si un contrato generado
sirve o estorba.

---

## 6. Ejecución asíncrona: la cola de inversiones

### 6.1 El problema que resuelve

`services/run_queue_service.py:1-6` lo enuncia sin rodeos:

> «El problema que mata al producto: `/v2/load-package` era SÍNCRONO → una inversión joint
> de 96k vóxeles (20+ min) revienta el proxy ("error interno del proxy") y deja al usuario
> sin feedback.»

### 6.2 El diseño

- **Worker = `multiprocessing.Process`** (spawn), máximo `TQ_INVERSION_WORKERS`
  (por defecto 1) simultáneos, cola FIFO en memoria.
- **Por qué procesos y no hilos**: «CPU-bound: el GIL castiga threads; un proceso aparte
  además permite CANCELAR de verdad (`terminate`) sin tocar el motor físico validado»
  (`services/run_queue_service.py:11-13`).
- **Por qué `Process` y no `ProcessPoolExecutor`**: «el pool no permite cancelar un trabajo
  en curso — la cancelación real del gate F3 manda»
  (`services/run_queue_service.py:15-17`).
- **El hijo importa el servicio, no `main.py`**, para que el arranque de `spawn` cargue lo
  mínimo (`services/run_queue_service.py:18-19`).
- **Cancelación en dos capas**: archivo cooperativo `cancel.requested` en el directorio de
  la corrida, más `terminate` (`services/run_queue_service.py:20-22`).
- **Progreso por el mecanismo nativo existente**: `update_run_status` → `schedule.json` →
  `GET /geophysics-status`, «cero infraestructura», sin Redis
  (`services/run_queue_service.py:6-9`).

**Valoración.** Las tres decisiones —procesos por cancelabilidad, `Process` en vez de pool
por la misma razón, y reutilizar el canal de progreso existente— están justificadas por
requisitos concretos y no por preferencia. Para un producto *local-first* que no puede
asumir un broker externo, es la arquitectura correcta.

### 6.3 La asimetría pendiente

La auditoría previa del propio proyecto registra que **la rama síncrona no entra en el
historial**: al lanzar 12 levantamientos por script, la pantalla de historial quedaba
vacía. Es decir, las dos rutas (síncrona y encolada) no son equivalentes en sus efectos
secundarios. **NO DETERMINADO** si sigue vigente: no se auditó `api/history_api.py`.

---

## 7. El paquete de scripting

`terraquantum/` expone el pipeline completo desde Python
(`terraquantum/__init__.py:1-20`):

```python
import terraquantum as tq
paquete = tq.enrich(gravity="survey.csv", config={"utm_zone": "19S"})
corrida = tq.run_inversion(paquete, project_id="cerro_x")
corrida.verdict["level"]      # veredicto reconciliado
corrida.best_target           # dónde perforar, con procedencia
corrida.depth_resolution      # y qué NO resuelve el dato
corrida.save_bundle("entrega/")
```

**La decisión arquitectónica clave**, declarada en el propio módulo
(`terraquantum/__init__.py:24-26`):

> «**Es un CLIENTE del backend**, no una segunda implementación. Por defecto monta la app
> en el propio proceso (ni servidor, ni puerto, ni red) y la recorre por [ASGI].»

Esto evita el modo de fallo más caro de este tipo de bibliotecas: una API de scripting que
reimplementa la orquestación y se desincroniza del servidor. Aquí, si el endpoint cambia,
el script cambia con él.

Nótese además que la API expone **deliberadamente** los tres campos que importan para la
honestidad: el veredicto, el blanco con su procedencia, y **qué no resuelve el dato**. El
diseño de la superficie pública comunica los límites en lugar de esconderlos.

---

## 8. Integración continua

`.github/workflows/ci.yml`. Lo distintivo es que **cada guarda existe porque se midió un
fallo concreto**:

| Guarda | El fallo que la motivó |
|---|---|
| `compile_check.py` propio | `compileall` compilaba «`Camiones` y `workers`, que no existen», avisaba por stdout y devolvía 0: la CI pasaba en verde compilando 6 de los 8 paquetes que decía |
| Versión de Python desde archivo | la CI fijaba 3.11 y `zarr==3.2.1` exige ≥3.12 → «la CI validaba un árbol de dependencias que nunca llega al cliente» |
| Cierre de dependencias | `psutil` dejó de ser instalable al quitar `distributed`, y eso puso 6 tests en rojo en un runner limpio |
| Presupuestos por AST | que una refactorización previa no se deshaga sola con el tiempo |
| Censo de configuración | detectar variables de entorno nuevas sin declarar |
| Duplicación estructural | umbral <40 ventanas duplicadas entre los dos motores (se bajó de 192 a 20) |
| Inventario de validación | que cada script declare si **decide** o sólo **mide** |

**Disparadores.** `branches: ["**"]` en push, con un comentario que explica el error previo:
con `["*"]` un push a `fix/lo-que-sea` no disparaba nada, porque en los filtros de GitHub
Actions `*` no cruza la barra. «Una red de seguridad que no cubre el nombre de rama que más
se usa no es una red de seguridad.»

**Regresión física nocturna.** `cron: "30 4 * * *"`, porque la suite completa cuesta «entre
33 min y 6,9 h MEDIDOS en dos corridas del propio gate», de modo que no cabe en un PR.

---

## 9. Estructura del frontend

- **Next.js / React / TypeScript**, con Three.js vía React-Three-Fiber.
- **Estado global con Zustand** (`store/useAppStore.ts`, 887 líneas).
- **Cliente de API centralizado** (`lib/terraquantum/frontendApi.ts`, 2.778 líneas).
- **Tipos generados** desde el backend, no escritos a mano.
- **Deshacer/rehacer por deltas** (`store/deshacible.ts`), con una decisión de diseño
  notable: el hueco de clasificación se cierra **por tipos**, de modo que un campo sin
  clasificar como deshacible o no-deshacible **no compila**. Es convertir una disciplina en
  una restricción del compilador.
- **Empaque de escritorio con Tauri** (`src-tauri/`), con el backend como *sidecar*.
- **Pruebas E2E con Playwright** (`e2e/*.spec.ts`).

### 9.1 Hallazgos previos del propio proyecto, útiles como contexto

La auditoría interna registra tres cosas medidas que un revisor debería conocer:

- **44 de 93 acciones del store no tienen llamador**, y `Scene3D` **lee ~19 perillas que
  ningún control puede mover**. Es decir, hay superficie de estado muerta.
- Un *listener* de teclado en `Scene3D` **secuestraba las flechas**, dejando 8 deslizadores
  inoperables.
- El empaque Tauri sirve en el **primer puerto libre entre 3000 y 3011**, de modo que
  `localStorage` —ligado al origen— puede vaciarse solo al cambiar de puerto.

El tercero es el más interesante arquitectónicamente: la persistencia del cliente depende
de un detalle de asignación de puertos.

---

## 10. Deuda técnica reconocida

El proyecto mantiene un registro explícito de complejidad no resuelta. Las cuatro funciones
que una fase de refactorización **nombró y no tocó**:

| Función | Líneas | Complejidad ciclomática |
|---|---|---|
| `solve_magnetic_inversion_lsqr` | 812 | 116 |
| `_import_gravity_csv_v1_impl` | 777 | 181 |
| `run_joint_inversion` | 736 | 87 |
| `run_magnetic_inversion` | 616 | 73 |

Y una que **sí** se partió: `solve_inversion_lsqr` pasó de 2.030 a 152 líneas y de
complejidad 183 a 12, «con byte-identidad y **sin reescribir una línea**» — los cuerpos se
movieron y las fronteras se determinaron por AST.

Ese método —mover en lugar de reescribir, con un arnés de identidad byte a byte como red—
es el correcto para código numérico, donde una reescritura «equivalente» puede cambiar el
resultado.

---

## 11. Problemas detectados

### 11.1 Una función testeada que producción no ejecuta

`select_solver` (`exploration/solver_preconditioned.py:34`) implementa la tabla de despacho
de solvers y tiene cinco tests (`tests/test_fase10_solver.py:56-71`). El despacho real está
escrito **en línea** en `exploration/gravimetry.py:2529-2535` y nunca la llama.

Hoy son lógicamente equivalentes, de modo que no hay error de comportamiento. Pero si
alguien cambiara el despacho real, la suite seguiría en verde. Es cobertura mal dirigida.

### 11.2 Documentación que describe código que ya no existe

Dos docstrings de `exploration/solver_preconditioned.py` (líneas 14-15 y 69-71) afirman que
el sistema llega con el *depth weighting* de Li & Oldenburg aplicado. El propio proyecto
demostró que ese peso se cancela algebraicamente y que el precondicionador real es la
ponderación por sensibilidad (`exploration/gravimetry.py:2253-2270`). Los docstrings
quedaron desactualizados.

Análogamente, el docstring de `VolumeRaymarchLayer` dice «when wired into Scene3D, a later
slice», pero la capa ya está montada (`terraquantum-web/componentes/Scene3D.tsx:1144`).

**Por qué importa más de lo habitual:** en un sistema científico, un docstring equivocado
puede llevar a un revisor a validar algo que no existe.

### 11.3 Acoplamiento de presentación en la capa de dominio

`services/isosurface_service.py` emite vértices **ya transformados al espacio visual de
Three.js** (centrados y con inversión del eje Y). La consecuencia es que
`services/omf_export_service.py:550-561` tiene que **deshacer la transformación del visor**
para producir coordenadas geográficas.

Un servicio de dominio que produce coordenadas de presentación, y otro que las revierte, es
acoplamiento indebido. El informe 09 §4 documenta una inconsistencia que probablemente
deriva de aquí.

### 11.4 Estado muerto en el frontend

44 de 93 acciones del store sin llamador, y ~19 perillas leídas por la escena que ningún
control puede mover. Superficie que hay que mantener sin que nadie la use.

---

## 12. Resumen técnico

### Bien resuelto

- Catálogo de 63 errores con severidad, mensaje en español y **acción sugerida**.
- Configuración inventariada por AST con guarda de CI, y parseo estricto tras medir tres
  modos de fallo reales.
- Banderas que declaran su **límite** y su **coste**, no sólo su efecto.
- Contrato backend–frontend **generado** desde el esquema, con `--check` de deriva y una
  justificación razonada de no añadir dependencia de npm.
- Cola de inversiones con procesos, cancelación real en dos capas y reutilización del canal
  de progreso existente, sin infraestructura extra.
- Paquete de scripting que es **cliente** del backend, no una segunda implementación, y que
  expone los límites en su superficie pública.
- CI donde cada guarda nace de un fallo medido.
- Orden de middleware documentado; aviso de configuración CORS insegura al arranque.
- Refactorización numérica por movimiento con red de identidad byte a byte.
- Deshacer/rehacer donde la clasificación se impone **por tipos** (no compila si falta).

### Problemas detectados

1. `select_solver` testeada pero no ejecutada.
2. Docstrings que describen un precondicionador y un cableado inexistentes.
3. Un servicio de dominio que emite coordenadas de presentación, y otro que las revierte.
4. Estado muerto en el frontend (44/93 acciones sin llamador).
5. Asimetría declarada entre la ruta síncrona y la encolada (historial) — **NO DETERMINADO**
   si sigue vigente.
6. Cuatro funciones con complejidad ciclomática entre 73 y 181, reconocidas y sin dueño.

---

## 13. Preguntas abiertas para revisión académica

---

### Pregunta 1 — Contratos duplicados y su verificación

**Pregunta.** El proyecto identificó que un contrato backend–frontend escrito a mano dos
veces «no tiene test posible, porque el test sería escribirlo por tercera vez», y lo
resolvió generando los tipos desde el esquema OpenAPI con un `--check` de deriva en CI.
¿Le parece el enfoque correcto? ¿Y cómo trataría el problema asociado: declarar
`response_model` **borra** campos no declarados si es estricto e **inyecta** nulos si es
permisivo, de modo que activar el contrato puede romper consumidores existentes?

**Evidencia.** `scripts/ci/generate_frontend_types.py:6-20`;
`terraquantum-web/types/backend-contracts.generated.ts` (1.201 líneas generadas).

---

### Pregunta 2 — Tests que no tocan el camino de ejecución

**Pregunta.** `select_solver` tiene cinco tests y ningún llamador en producción; el despacho
real está duplicado en línea en otro archivo. ¿Qué peso le daría a este tipo de cobertura
mal dirigida, y qué mecanismo usaría para detectarla sistemáticamente — cobertura de rama
sobre la ruta real, análisis de llamadores en CI, o simplemente prohibir la duplicación?

**Evidencia.** `exploration/solver_preconditioned.py:34`;
`tests/test_fase10_solver.py:56-71`; `exploration/gravimetry.py:2529-2535`.

**Nota.** El proyecto **ya tiene** un guard de duplicación estructural entre los dos motores
de física. La pregunta es si el mismo instrumento debería cubrir este caso.

---

### Pregunta 3 — Deriva entre documentación y código en software científico

**Pregunta.** Dos docstrings afirman que el sistema aplica el *depth weighting* de Li &
Oldenburg, cuando el propio proyecto demostró que se cancela algebraicamente. En software
ordinario un comentario obsoleto es ruido; aquí puede hacer que un revisor **valide algo
que no existe**. ¿Qué mecanismo recomendaría — *doctests* sobre las afirmaciones
verificables, enlazar cada afirmación a un test que la sostenga, o una revisión periódica de
los docstrings que citan literatura?

**Evidencia.** `exploration/solver_preconditioned.py:14-15` y `69-71` frente a
`exploration/gravimetry.py:2253-2270`.

---

### Pregunta 4 — Dónde debe vivir la transformación a espacio de presentación

**Pregunta.** `isosurface_service` emite vértices ya centrados y con inversión de Y para
Three.js, y por eso el exportador OMF tiene que **invertir la transformación del visor**
para georreferenciar. ¿Recomendaría que la capa de dominio emita siempre coordenadas
físicas y que toda conversión a presentación viva en el cliente, aunque cueste recorrer los
vértices allí?

**Evidencia.** `services/isosurface_service.py:380-395`;
`services/omf_export_service.py:550-561`.

**Contexto.** El informe 09 §4 documenta una inconsistencia entre capas que probablemente
deriva de este reparto de responsabilidades.

---

### Pregunta 5 — Complejidad ciclomática reconocida y sin dueño

**Pregunta.** Cuatro funciones tienen complejidad entre 73 y 181 y están nombradas como
deuda. Una quinta se partió con éxito de 183 a 12 **moviendo cuerpos, sin reescribir**, con
un arnés de identidad byte a byte como red. ¿Es ese método —mover, no reescribir,
verificando el hash de los bits— generalizable, o hay un punto en que la reescritura es
inevitable? ¿Y qué umbral de complejidad consideraría aceptable para código numérico, donde
partir una función puede cambiar el orden de operaciones?

**Evidencia.** Presupuestos por AST en `.github/workflows/ci.yml`;
`exploration/potential_field_core.py:35-38` (el contrato de identidad).

---

### Pregunta 6 — Una API de scripting como cliente del propio backend

**Pregunta.** El paquete `terraquantum` monta la aplicación ASGI en el mismo proceso y la
recorre sin red, para no reimplementar la orquestación. ¿Le parece el patrón correcto?
Ventaja evidente: imposible desincronizarse del servidor. Posible desventaja: el usuario de
la biblioteca carga toda la aplicación web —routers, middleware, dependencias— para hacer
una inversión.

**Evidencia.** `terraquantum/__init__.py:24-26`.

---

### Pregunta 7 — Local-first y sus consecuencias

**Pregunta.** El producto se empaqueta con Tauri y el backend como *sidecar*, sirviendo en
el primer puerto libre entre 3000 y 3011. Como el `localStorage` del navegador está ligado
al origen (y por tanto al puerto), las preferencias del usuario **pueden vaciarse solas** al
cambiar de puerto entre arranques. ¿Qué recomendaría: fijar el puerto y fallar si está
ocupado, o migrar la persistencia al sistema de archivos vía la API de Tauri?

---

### Pregunta 8 — Estado muerto como síntoma

**Pregunta.** 44 de 93 acciones del store no tienen llamador, y la escena 3D lee ~19
perillas que ningún control puede mover. ¿Lo trataría como deuda menor —código que sobra— o
como síntoma de un problema de diseño del estado: un store que crece por acumulación en
lugar de por necesidad? ¿Y qué guarda automática usaría para impedir que reaparezca?

---

*Fin del informe 08. El informe 07 trata el rendimiento y el paralelismo; el 11, la
persistencia y los formatos; el 12, la arquitectura de pruebas y su alcance real.*
