# 08 — API de scripting (`terraquantum`) · **v0**

*Fase 11 del plan técnico (`docs/06_AUDITORIA_TECNICA_INTEGRAL.md` §10). Este
documento es la **promesa de estabilidad escrita** que esa fase exige como
criterio de aceptación; un test del backend comprueba que existe y que declara
la misma versión que el código (`terraquantum.API_VERSION`).*

---

## 1. Para quién es

Para el consultor geofísico que **repite el mismo flujo muchas veces al año** y
no quiere hacerlo a mano doce veces. Es el usuario que el proyecto declara como
comprador (`docs/00_INVESTIGACION_MERCADO.md`): experto, con poco soporte, que
valora más *«procesa estos 12 surveys con la misma configuración»* que varias
funciones de interfaz.

```python
import terraquantum as tq

paquete = tq.enrich(gravity="survey.csv", config={"utm_zone": "19S"})
corrida = tq.run_inversion(paquete, project_id="cerro_x")

print(corrida.verdict["level"], corrida.best_target, corrida.depth_resolution)
corrida.save_bundle("entrega/")
```

Instalación: no hay. El módulo vive dentro del backend, que es quien tiene el
motor.

```python
import sys; sys.path.insert(0, "<ruta>/terraquantum-backend")
import terraquantum as tq
```

o, equivalente, `cd terraquantum-backend && python mi_script.py`. Ejemplos
ejecutables en `terraquantum-backend/examples/`.

---

## 2. Qué es por dentro (y por qué importa saberlo)

**Es un cliente de los endpoints del backend, no una segunda implementación.**
Por defecto monta la aplicación FastAPI **en el propio proceso** —sin servidor,
sin puerto, sin red— y recorre los MISMOS endpoints que usa la interfaz web.

Se decidió así midiendo. El camino dorado **no vive entero en `services/`**:
`POST /v2/gravity-import/load-package` tiene ~250 líneas de orquestación en el
propio handler HTTP (grilla efectiva, ruteo magnético, σ por estación,
topografía condicional, persistencia de sondajes, presupuesto de vóxeles). Una
API que reconstruyera eso llamando a los servicios sería una segunda
implementación del camino dorado — y este proyecto ya sabe cómo acaba eso: H-29
fue un movimiento multi-campo escrito a mano en dos sitios que divergieron.

Consecuencia comprobable, y hay un test que la comprueba comparando payloads:
**la API de scripting y la interfaz recorren el mismo código.** Cuando cambia el
motor, cambian las dos, o falla el test.

Para hablar con un backend ya levantado (el de la app de escritorio, o uno en
Docker):

```python
sesion = tq.Session(base_url="http://127.0.0.1:8000", api_key="…")
tq.enrich(gravity="survey.csv", session=sesion)
```

---

## 3. Qué promete la v0

**v0 significa que las firmas pueden cambiar.** Está declarado a propósito:
publicar una API es un compromiso, y prometer estabilidad antes de que la use
alguien es prometer de más. El propio informe de auditoría lo pedía así
(*«conviene marcarla v0 explícitamente para no congelar firmas»*).

Lo que **sí** se promete en v0:

| Promesa | Alcance |
|---|---|
| **El camino dorado no cambia de forma** | `enrich → run_inversion → Run` seguirá siendo la secuencia. Podrán añadirse parámetros con valor por defecto; no se quitarán pasos. |
| **Nada se rompe en silencio** | Un fallo del backend es SIEMPRE una excepción con `code` del catálogo. Un resultado nunca es un valor plausible por defecto. |
| **`code` es el contrato, no el texto** | Los `user_message` están en español y pueden reescribirse; los `code` (`CSV_EMPTY`, `INSUFFICIENT_DATA`, `RATE_LIMITED`…) son el identificador estable sobre el que un script decide. |
| **Cero física propia** | Esta capa no calcula, no umbraliza y no tiene defaults propios. Los valores por defecto son los del backend, que es donde están medidos. Si el motor cambia un default, la API lo hereda — no lo congela. |
| **El paquete TQPKG es el artefacto reproducible** | `Package.save()` / `Package.from_file()` escriben y leen con el parser del backend. Un paquete guardado hoy define la corrida entera. |

Lo que **no** se promete en v0:

* Que los nombres de los métodos no cambien. Si algo se renombra, se anunciará
  en el `CHANGELOG.md` del backend con la traducción.
* Que los diccionarios devueltos por el backend (`report`, `block_model`,
  `misfit`…) mantengan sus claves. **Son el contrato del backend, no de esta
  capa**, y esta capa los pasa tal cual a propósito: envolverlos crearía un
  segundo contrato que divergiría del primero.
* Estabilidad de `terraquantum.admin`, que es administración del despliegue.

### Qué haría falta para llamarla v1

1. Que la usen usuarios reales durante un ciclo de trabajo completo y que la
   forma sobreviva a ese contacto.
2. Que los dos hallazgos que esta misma API destapó (§6) estén cerrados: hoy un
   script puede corromper geometría en silencio con un CSV `X,Y,Z`, y eso es
   incompatible con prometer estabilidad.
3. Que la asimetría gravimetría/magnetometría del informe (§5) esté resuelta o
   declarada como permanente: hoy `Run.verdict` es `None` en magnetometría
   porque **el informe magnético no publica veredicto**, no porque falte
   cablearlo aquí.

---

## 4. Superficie pública

Todo lo exportado está en `terraquantum.__all__`; un test exige que **cada
símbolo de esa lista se ejercite** en la suite.

### Camino dorado

| Función | Endpoint que envuelve | Qué hace |
|---|---|---|
| `analyze_columns(csv)` | `POST /v2/gravity-import/analyze-columns` | Cómo se van a leer las columnas. No invierte. |
| `parse_rows(csv)` | `POST /v2/gravity-import/parse-rows` | Filas ya parseadas por el pipeline oficial (encoding, separador, coma decimal). |
| `enrich(...)` | `POST /v2/gravity-import/enrich-package` | CSV(s) crudos → `Package` TQPKG, derivando con física real. |
| `run_inversion(pkg)` | `POST /v2/gravity-import/load-package` | Paquete → modelo 3D persistido. |
| `batch(surveys, config=…)` | las dos anteriores, N veces | El lote con configuración común. |
| `invert_field_csv(csv)` | `POST /v2/gravity-import/invert-with-corrections` | Gravimetría CRUDA → correcciones + inversión en una llamada. |
| `estimate_depth(stations)` | `POST /v2/depth-estimate` | Euler + espectro radial, independiente de la inversión. |
| `open_run(p, r)` / `list_runs()` | `/geophysics-status`, `/v2/history/runs` | Re-abrir corridas anteriores sin re-invertir. |

### `Run`

`wait()` · `cancel()` · `status_now()` · `report` · `verdict` · `best_target` ·
`depth_resolution` · `fit` · `chi2` · `misfit_pct` · `misfit()` ·
`convergence()` · `block_model()` · `block_model_frame()` · `isosurface()` ·
`section()` · `profile()` · `save_bundle()` · `save_block_model_csv()` ·
`save_report()`.

### Errores

`TerraquantumError` (base, con `code` / `suggested_action` / `details`),
`NeedsColumnMapping` (una PREGUNTA con el plan adjunto, no un fallo),
`RateLimited`, `InversionFailed`, `RunTimeout`.

---

## 5. Cosas que hay que saber antes de escribir el primer script

Todas MEDIDAS al construir la fase. Están aquí porque cuestan horas si se
descubren solas.

**El límite de peticiones muerde el caso de uso principal.** El informe justifica
la fase con «12 surveys»; por el camino natural eso falla en el **número 11** con
`429 Rate limit exceeded: 10 per 1 minute`, y la respuesta **no trae
`Retry-After`**, así que un cliente no puede saber cuánto esperar. Por eso
`Session` tiene política explícita: `"reset"` (default **en proceso**, donde el
limitador no protege ningún perímetro porque el «cliente remoto» es el propio
script), `"wait"` (default **remoto**, con backoff ciego 5→10→20→40 s) y
`"raise"`.

**`wait=False` exige `if __name__ == "__main__":`.** El worker se lanza con
`multiprocessing` en modo *spawn*, que RE-IMPORTA el módulo principal. Medido sin
el guard: el encolado responde `queued`, el hijo re-ejecuta el script entero, su
propio encolado muere en el `RuntimeError` del `freeze_support()` y la corrida
acaba en `interrumpida`. La API traduce eso a `SPAWN_REQUIRES_MAIN_GUARD` con su
acción, pero no puede evitarlo: es la biblioteca estándar.

**Gravimetría y magnetometría publican informes DISTINTOS**, no dos versiones del
mismo. `overall_verdict`, `best_target` y `depthResolution` (la trilogía honesta
B1/B2/B3) **sólo existen en gravimetría**; magnetometría publica
`report["solver"]`. `Run.verdict` devuelve `None` en magnetometría porque es la
verdad. Para el χ² sin importar la física, `Run.chi2`.

**`nx/ny/nz` y `depth` van juntos.** Fijar la malla y dejar la profundidad
automática produce rechazos en los dos extremos: DO-27 con `depth=900` («máxima
física: 224 m») y Laguna del Maule con malla 8×8×6 y `depth` automático
(«depth=5023 m … máxima física: 4160 m»). El motivo es que `load-package` toma la
malla del paquete y la profundidad del auto-grid, que se calculó para otra malla.
**Lo natural para un lote es no fijar ninguna de las dos** y dejar que el
auto-grid decida por survey.

**El motor imprime por `stdout`.** `[F0.9 TENSOR MESH]`, `[FOCUSING]`, `[GPCG]`,
`[BLOCK-MODEL-*]` y los eventos de `structlog` salen por consola durante la
corrida. No hay modo silencioso y **no se promete uno**: silenciar `structlog`
no callaría los `print()` del motor, y una promesa a medias es peor que ninguna.

**Un survey real tarda minutos.** MEDIDO en la máquina de referencia, Laguna del
Maule (191 estaciones, CSV crudo): malla 6×6×5 ≈ 8 s, 12×12×8 ≈ 4 min. El coste
lo dominan la densidad del kernel y la memoria, no el número de vóxeles
(`run_queue_service` lo documenta con sus mediciones).

---

## 6. Lo que esta API destapó y NO arregla

El informe anticipaba que *«la propia API se vuelve el mejor test de integración
del proyecto»*. Lo fue el primer día. Los dos hallazgos son del **backend**, no
de esta capa, y se registran aquí porque un script los va a pisar:

**H-F11-1 · Un CSV `X,Y,Z` corrompe la geometría en silencio (🔴 alto).**
`X,Y,Z` es el encabezado de los dos benchmarks magnéticos publicados. El
auto-mapeo asigna `{x: X, y: Z, depth: Y}`: el northing queda en el rol
PROFUNDIDAD y la elevación constante en el rol norte. La guarda que existe para
exactamente esto (`northing_in_depth_slot`) exige `> 1e5 m`, así que dispara con
DO-27 (northing 7,1e6) y **no dispara con Raglan** (4,1e4, coordenadas locales):
`needs_mapping=False`, `needs_confirmation=False`, `suspicions=[]`. Río abajo
muere con *«El kernel magnético G_active quedó vacío. Revisa cutoff_radius…»*,
que señala el sitio equivocado. **Mitigación hoy: pasar `column_map` explícito.**

**H-F11-2 · El auto-grid propone mallas que el esquema rechaza (🟠 medio).**
Con el mapeo ya correcto, el auto-grid de Raglan propone `nx=82, nz=81` y
`GeophysicsInvertInput` exige `≤ 80`: el usuario recibe un error crudo de
Pydantic con una URL de `errors.pydantic.dev` en vez de un mensaje del catálogo.
La asimetría está a la vista en `load-package::_eff_dim`, que **acota el valor
del usuario a 1..80 y devuelve el automático sin acotar**.

**H-F11-3 · Una corrida síncrona no entra en el historial (🟠 medio).**
La rama `sync=true` de `load-package` —la que el propio endpoint recomienda
«para tests de contrato / scripts», y el default de `run_inversion`— escribe
`schedule.json` pero **no llama a `project_store.record_run`**. La rama de la
cola sí. Consecuencia para el usuario: **un consultor procesa doce surveys
desde un script y la pantalla «Historial» no muestra ninguno**; los modelos
están en disco y `open_run()` los recupera por id, pero el listado sale vacío.
Contraste medido: la misma corrida con `wait=False` aparece con estado, ruta y
tiempos.

Ninguno de los tres se arregla en la Fase 11 a propósito: son conducta de la
ingesta, del esquema y de la persistencia, tocarlos cambia el camino dorado de
**todos** los usuarios, y esta fase no cambia payloads que no le corresponden.
Que el cliente escribiera el historial, además, sería la API fabricando una
persistencia que el backend no hizo. Los tres quedan pinchados por tests de
caracterización en `tests/test_fase11_api_scripting.py`, que se pondrán rojos el
día que alguien los arregle.

---

## 7. Los cuatro datasets canónicos por el camino del usuario

`examples/02_datasets_canonicos.py` los recorre. Estado medido:

| Dataset | Física | Por el camino del usuario |
|---|---|---|
| Laguna del Maule | gravedad | ✅ desde el CSV **crudo de Excel-ES** (preámbulo, `;`, coma decimal, cabeceras en español) |
| DO-27 kimberlita | gravedad | ✅ |
| Raglan Ni-Cu | magnetismo | ✅ **con `column_map` explícito** (ver H-F11-1) |
| San Nicolás VMS | gravedad | ❌ **no evaluable**: su dato es `data/external/san_nicolas/realdata.mat`, que ni está versionado (`data/` va en `.gitignore`) ni es un CSV, y el repositorio no tiene conversor de `.mat`. La suite F9 lo cubre re-invirtiendo sus observaciones guardadas. |

Y lo que este recorrido **no** demuestra: recorrer el camino no es validar la
física. Los benchmarks se validan en `pytest -m validation` (suite F9) contra
verdad publicada con tolerancias medidas. Son dos preguntas distintas y las dos
hacen falta.
