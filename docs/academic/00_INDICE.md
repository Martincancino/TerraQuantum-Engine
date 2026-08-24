# Expediente científico-técnico de TerraQuantum
## Documentación para revisión académica externa

**Autor del sistema:** Martín Cancino — Ingeniería Civil de Minas
**Fecha de esta compilación:** 21 de agosto de 2026
**Rama auditada:** `fases-19-25-cierre`
**Commit de referencia:** `c810ed5`

---

## 1. Qué es este documento y qué no es

Esto **no** es documentación para programadores, ni un informe comercial, ni una
presentación de ventas. Es un expediente técnico escrito con un objetivo concreto y
poco habitual: **que un especialista externo pueda encontrar los errores**.

TerraQuantum es un sistema de inversión geofísica de campos potenciales (gravimetría
y magnetometría) orientado a exploración minera, con visualización 3D y un flujo de
usuario completo desde un CSV de campo hasta un modelo de subsuelo. Lo escribió una
sola persona, estudiante de segundo año de Ingeniería Civil de Minas, sin formación
formal previa en geofísica computacional. Esa circunstancia no es una excusa: es
información relevante para el revisor, porque indica dónde es más probable que haya
errores conceptuales y no sólo errores de implementación.

Cada informe de esta carpeta intenta responder, para su disciplina:

- qué hace exactamente el código;
- qué matemática y qué física utiliza, escritas explícitamente;
- qué supuestos hace, incluidos los que no están declarados en ninguna parte;
- qué significa cada resultado y qué **no** significa;
- qué limitaciones existen;
- qué está implementado, qué está a medias y qué está declarado pero muerto;
- y qué preguntas concretas sería útil que un especialista respondiera.

---

## 2. Reglas epistémicas con las que se escribió

Estas reglas se aplicaron de forma estricta, y conviene que el revisor las conozca
para saber cuánto peso dar a cada afirmación.

**Regla 1 — La fuente de verdad es el código ejecutable.**
No la documentación del proyecto, no los comentarios, no los nombres de las
funciones. Cuando la documentación interna y el código discrepan, se documenta la
discrepancia y gana el código.

**Regla 2 — Toda afirmación lleva coordenadas.**
Cada aserción técnica cita `archivo:línea`. Si el lector quiere verificar, puede
abrir exactamente ese punto. Las referencias son a la rama y commit indicados
arriba.

**Regla 3 — "NO DETERMINADO" es una respuesta válida.**
Cuando no se pudo establecer un hecho leyendo el código, se escribe literalmente
*NO DETERMINADO* y se indica qué se intentó. No se rellenan huecos con suposiciones
plausibles. Un hueco declarado es información; un hueco tapado es ruido.

**Regla 4 — Se distinguen tres niveles de afirmación.**
Este es probablemente el punto más importante de todo el expediente:

| Nivel | Pregunta que responde | Ejemplo |
|---|---|---|
| **(a) Lo que el código hace** | ¿Qué operación aritmética ocurre? | "Se minimiza `‖W_d(Gm−d)‖² + λ²‖m̃‖² + λ_sp²‖L·W_s·m̃‖²`" |
| **(b) Lo que matemáticamente significa** | ¿Qué propiedad tiene esa operación? | "Es una regularización de Tikhonov con seminorma de curvatura; los campos constantes están en el núcleo de `L`" |
| **(c) Lo que se puede afirmar del mundo** | ¿Qué se puede decir de la roca? | "Existe una distribución de contraste de densidad compatible con los datos. **No** se puede afirmar que sea la real, ni que corresponda a mineralización" |

El sistema, y esta documentación, tienden a colapsar (a) en (c) si nadie lo impide.
Buena parte del trabajo de estos informes es mantener los tres niveles separados.

**Regla 5 — Los problemas se documentan, no se arreglan en silencio.**
Cuando la auditoría encontró algo que parece incorrecto o discutible, se describe el
problema, dónde ocurre, por qué podría importar y qué impacto tendría — antes de
proponer cualquier solución.

---

## 3. Estado de esta compilación (honestidad sobre la propia documentación)

Este expediente se está construyendo **por partes**, y conviene decirlo con
claridad porque afecta a cuánto puede confiar el lector en cada informe.

### 3.1 Cómo se hizo la auditoría

Se intentó primero una auditoría automatizada en paralelo sobre 14 subsistemas.
Falló por completo por un límite de cuota de la cuenta, y **ningún resultado de esa
vía se usó**. La auditoría que respalda estos informes es lectura directa del código,
archivo por archivo, hecha secuencialmente. Es más lenta y cubre menos superficie por
unidad de tiempo, pero tiene una propiedad valiosa: **todo lo que se afirma aquí se
leyó de verdad**.

### 3.2 Cobertura verificada hasta el momento

Módulos **leídos en su totalidad o en sus secciones críticas**, y por tanto base
sólida de los informes ya escritos:

| Módulo | Alcance leído |
|---|---|
| `exploration/potential_field_core.py` | **Completo** (883 líneas) |
| `exploration/solver_preconditioned.py` | **Completo** (388 líneas) |
| `exploration/gravimetry.py` | Kernel directo, Laplaciano, cadena de pesos, ensamblado, despacho de solver, bucle IRLS, ambos selectores de λ, guarda de memoria |
| `exploration/magnetometry.py` | Vector de campo, kernels dipolar y de prisma, prefactores, remanencia |
| `services/geophysics_service.py` | Selección de λ en producción, veredicto de confianza, procedencia de la ley |
| `core/config.py` | Semántica de las banderas de solver y su medición |
| `services/gravity_import_service.py` | Asignación de roles de coordenadas (parcial) |
| `services/omf_export_service.py` | Mapeo de ejes a georreferencia (parcial) |
| `services/gravity_corrections_service.py` | **Completo** — toda la cadena de reducción |
| `exploration/implicit_modeling.py` | Kernel HRBF, ajuste, prior espacial, límites declarados |
| `services/borehole_desurvey_service.py` | Desurvey por curvatura mínima, QA/QC, convenciones |
| `services/isosurface_service.py` | Marching cubes, Taubin, orientación, LOD |
| `services/block_model_service.py` | Modos, estadísticas, exportación (sin economía) |
| `reporting/report_generator.py` | Descargo regulatorio y tarjetas de métricas |
| `api/chat_api.py` | Escudo de cumplimiento JORC/NI 43-101 |
| `terraquantum-web/lib/terraQuantumGeology.ts` | **Completo** (650 líneas) |
| `terraquantum-web/lib/render/IsosurfaceMeshLayer.tsx` | **Completo** |
| `terraquantum-web/componentes/Scene3D.tsx` | Montaje de capas, grupo, cortes, picking, centro del modelo |
| `terraquantum-web/lib/render/gpuCapabilities.ts`, `VolumeRaymarchLayer.tsx` | Contratos y degradación |
| `services/export_service.py` | **Ambas rutas UBC-GIF**, GSLIB, bundle ZIP, manifiesto |
| `services/omf_export_service.py` | Permutación de ejes, decisión de dependencia |
| `main.py`, `core/errors.py`, `core/rate_limit.py` | Composición HTTP, catálogo de 63 errores |
| `services/run_queue_service.py`, `terraquantum/__init__.py` | Cola en procesos, API de scripting |
| `scripts/ci/generate_frontend_types.py`, `exploration/storage.py` | Generación de contratos, formatos |
| `exploration/checkerboard_test.py` | Metodología, métricas y generación de ruido |
| `scripts/validation/GATES.json` | **Completo** — 71 scripts clasificados |
| `.github/workflows/ci.yml`, `pytest.ini` | Guardas de CI y marcadores de coste |
| `terraquantum-web/lib/terraquantum/frontendApi.ts` | Construcción de celdas desde Arrow (parcial) |

**Los doce informes están escritos.** Ninguno se redactó sobre código no leído; donde la
lectura no alcanzó, el texto dice *NO DETERMINADO*.

**Lo que sigue sin auditar en profundidad**, y por tanto se declara como tal dentro de los
informes que lo tocan: `services/joint_inversion.py` y `exploration/pgi_engine.py`
(inversión conjunta y PGI), la mitad interna de la ingesta de CSV
(`services/csv_*.py`, `column_mapping_service.py`), `api/history_api.py`, y la mayor parte
de los 22 módulos de `api/` más allá de su inventario.

**Mediciones propias ejecutadas** (scripts en Python puro, sin modificar el proyecto ni
instalar dependencias): comparación numérica de la corrección de terreno implementada
contra la formulación clásica de columna vertical — resultados en el informe 04 §4.5.3.

Módulos **aún no auditados en profundidad** en el momento de escribir esta versión
del índice — los informes que dependan de ellos lo declararán explícitamente:

`exploration/magnetometry.py` · `services/joint_inversion.py` ·
`exploration/pgi_engine.py` · toda la cadena de correcciones gravimétricas y geodesia ·
la ingesta de CSV · `exploration/implicit_modeling.py` y sondajes ·
`services/block_model_service.py` y modelamiento minero · la capa de API y esquemas ·
el frontend salvo lo indicado · la suite de tests y arneses de validación ·
persistencia, formatos e interoperabilidad OMF.

> **Nota para el revisor:** si un informe de esta carpeta todavía no existe, o existe
> con una advertencia de cobertura al inicio, es porque el código que describe aún no
> se ha leído con el detalle que exige la Regla 2. Preferimos una carpeta incompleta y
> honesta a una carpeta completa y especulativa.

---

## 4. El sistema en una página

TerraQuantum es un monorepo con dos mitades y una separación estricta entre ellas:

```
TerraQuantum/
├── terraquantum-backend/     Python · FastAPI · ~128.000 líneas
│   ├── exploration/          Los motores de física e inversión (el núcleo científico)
│   ├── services/             Orquestación, correcciones, ingesta, exportación
│   ├── api/                  22 módulos de endpoints HTTP
│   ├── schemas/              Contratos Pydantic (fuente de los tipos del frontend)
│   ├── core/                 Configuración, errores, autenticación, métricas
│   ├── terraquantum/         Paquete de scripting en Python (API de usuario)
│   ├── tests/                Suite de pruebas
│   └── scripts/validation/   Arneses de validación contra datos reales
└── terraquantum-web/         Next.js · React · TypeScript · Three.js · ~35.000 líneas
    ├── componentes/          UI, incluida la escena 3D
    ├── lib/                  Cliente de API, render, historial, atajos
    ├── store/                Estado global (Zustand)
    └── src-tauri/            Empaque de escritorio local-first
```

**Regla arquitectónica declarada del proyecto:** toda la física, la matemática y los
cálculos ocurren en el backend. El frontend sólo visualiza y consume APIs. El
informe 08 y el informe 10 examinan hasta qué punto esa regla se cumple realmente
(adelanto: hay excepciones que importan, y están en la capa de visualización).

### 4.1 El flujo científico, de extremo a extremo

```
CSV de campo (sucio)
      │  detección de delimitador, decimal, unidades, sistema de coordenadas
      ▼
Mapeo de columnas por ROL  ──────────────────────────► informe 11
      │
      ▼
Correcciones gravimétricas  ─────────────────────────► informes 03, 04
      │  deriva · marea · latitud · aire libre · Bouguer · terreno
      ▼
Anomalía + malla de vóxeles (auto-grid)
      │
      ▼
MODELO DIRECTO   G ∈ ℝ^(n_obs × n_celdas)  ─────────► informes 02, 03
      │  Nagy (1966) campo cercano + masa puntual campo lejano
      ▼
PROBLEMA INVERSO  min ‖W_d(Gm−d)‖² + λ²‖m̃‖² + λ_sp²‖L m‖²  ──► informes 01, 02, 04
      │  LSQR / LSMR / TRF con bounds · IRLS opcional · λ por Morozov u operating point
      ▼
Modelo de contraste de densidad  m ∈ ℝ^(n_celdas)   [t/m³]
      │
      ▼
Diagnósticos de incertidumbre  ──────────────────────► informe 12
      │  DOI · checkerboard · null-space shuttle · σ posterior · veredicto de confianza
      ▼
Visualización 3D + interpretación  ──────────────────► informes 09, 10
      │  ⚠ aquí ocurren decisiones de normalización que afectan lo que se ve
      ▼
Ranking de blancos de perforación                    ──► informes 05, 06
```

---

## 5. Los doce informes y a quién van dirigidos

La idea central de este expediente es que **ningún profesor necesita entender
TerraQuantum entero**. Cada informe está escrito para poder leerse solo, sin haber
leído los demás. Si eso obliga a repetir una explicación en dos informes, se repite,
pero desde la perspectiva de cada disciplina.

| # | Informe | Perfil de revisor ideal | Pregunta central que le hacemos |
|---|---|---|---|
| 01 | Matemática | Matemática aplicada, análisis, optimización | ¿El funcional que se minimiza es el adecuado para este problema mal planteado? |
| 02 | Álgebra lineal y métodos numéricos | Álgebra lineal numérica | ¿El solver, el precondicionamiento y los criterios de parada son correctos y estables? |
| 03 | Física | Física, electromagnetismo, gravitación | ¿La formulación del campo potencial y sus aproximaciones son válidas? |
| 04 | Geofísica | Geofísica aplicada, métodos potenciales | ¿El flujo adquisición→inversión→interpretación es defendible? |
| 05 | Geología y modelamiento del subsuelo | Geología estructural, modelamiento implícito | ¿Los supuestos geológicos son razonables? ¿Qué falta para interpretar? |
| 06 | Modelamiento minero | Ingeniería de minas, evaluación de yacimientos | ¿Qué de esto es real y qué es un proxy de demostración? |
| 07 | Computación científica | Computación científica, HPC | ¿La discretización, la complejidad y la estabilidad numérica son adecuadas? |
| 08 | Ingeniería de software y arquitectura | Ingeniería de software | ¿La arquitectura sostiene un producto científico verificable? |
| 09 | Geometría computacional y 3D | Geometría computacional, gráficos | ¿Las transformaciones, mallas y superficies son correctas? |
| 10 | Visualización y renderizado | Gráficos por computador, visualización científica | ¿La visualización representa honestamente el resultado numérico? |
| 11 | Datos, persistencia y rendimiento | Sistemas, bases de datos, rendimiento | ¿Los datos son reproducibles y el sistema escala? |
| 12 | Validación científica, testing e incertidumbre | Estadística, metodología científica | ¿Lo que se llama "validación" lo es? ¿La incertidumbre está bien comunicada? |

---

## 6. Cómo usar este expediente (propuesta de trabajo)

La propuesta al revisor no es "lea todo y opine". Es más acotada y, creemos, más
útil para ambas partes:

1. **Lea sólo el informe de su disciplina.** Está escrito para ser autocontenido.
2. **Vaya directo a la última sección: "Preguntas abiertas para revisión académica".**
   Cada pregunta viene con: por qué surge, la evidencia en el código, qué sabemos
   hoy, qué **no** sabemos, y qué tipo de opinión sería útil.
3. **Conteste sólo lo que le parezca claro.** Una sola respuesta del tipo *"esta
   formulación tiene un problema conocido, mire X"* vale más que una revisión
   completa y superficial.

El objetivo declarado es cerrar este ciclo:

```
pregunta del profesor → problema detectado → cambio en el código →
experimento medido → resultado → nueva conclusión documentada
```

Si un revisor lee un informe y concluye *"aquí hay una idea razonable, pero esta
parte debería cambiarse por X"*, eso **no es un fracaso del proyecto**. Es
exactamente el resultado que se busca.

---

## 7. Advertencia sobre el vocabulario

Tres términos aparecen constantemente y conviene fijarlos desde el principio, porque
el sistema los usa con un significado preciso que no siempre coincide con el uso
coloquial:

- **Verificación** ≠ **Validación.** Verificación es "el software hace lo que el
  código dice". Validación es "el resultado corresponde a la realidad física". El
  informe 12 mantiene esta distinción de forma estricta y señala dónde el proyecto
  la ha confundido.

- **"Ley" (grade).** El sistema publica un campo llamado `grade`, pero acompañado de
  `"grade_source": "heuristic_gravity_proxy"`, `"assay_supported": false` y
  `"economically_validated": false`
  (`services/geophysics_service.py:614`), y de `"is_demo_grade": true`
  (`services/geophysics_service.py:830`). **No es una ley mineral.** Es un índice
  derivado del contraste de densidad. El informe 06 desarrolla esto.

- **"Confianza" (confidence).** El sistema emite un nivel `LOW`/`MEDIUM`/`HIGH`, y
  desacopla explícitamente la confianza **horizontal** de la **vertical**: la
  profundidad se marca `LOW` por defecto salvo que exista un dato independiente
  (`services/geophysics_service.py:800-810`). El informe 12 examina si el mecanismo
  hace lo que dice.

---

## 7 bis. Hallazgos que un revisor debería mirar primero

Si un profesor sólo tiene tiempo para mirar una cosa, que sea ésta. Son los hallazgos
que la auditoría considera más consecuentes, ordenados por gravedad, con el informe
donde se desarrollan.

| # | Hallazgo | Informe | Estado |
|---|---|---|---|
| **0** | **La corrección de terreno usa el módulo de la atracción en vez de su componente vertical.** Calcula $G\rho A|\Delta h|/r^2$; la formulación clásica de columna vertical da $\approx G\rho A\Delta h^2/(2r^3)$. La razón es $2r/|\Delta h|$, **crece con la distancia**, y el radio de integración por defecto es 22 km. **Medido**: 200× a 1 km con 10 m de desnivel; **12× en el total** de un cono de 500 m. La TC se **suma** a la anomalía y está **activa por defecto**. La señal buscada es de 0,1–10 mGal. | 04 §4.5, 12 §5.2 | **MEDIDO** con script propio. Falta cuantificar el efecto E2E. |
| **1** | **La proyección horizontal del campo geomagnético parece estar rotada 90°.** La ingesta (`lon→x`) y la exportación (`x→easting`) fijan $x$=Este, $z$=Norte; el módulo magnético documenta y usa $x$=Norte, $z$=Este. La gravimetría es invariante a esa permutación —usa sólo la componente vertical— por lo que el defecto es invisible en gravedad. Los dos benchmarks magnéticos externos son árticos ($\cos I\approx0{,}11$), donde el efecto sería mínimo; el caso de uso declarado es Chile ($\cos I\approx0{,}87$), donde sería máximo. | 03 §7 | Indicado por lectura de código en 3 sitios. **Sin experimento que lo confirme.** |
| **2** | **El solver iterativo agota siempre su límite de iteraciones.** Medido: `istop=7` en 500/500 corridas. El resultado publicado no es el minimizador del funcional declarado, sino el punto donde el método de Krylov se detuvo. El efecto medido sobre el resultado fue del 66–86 %. El sistema lo detecta y lo declara al usuario. | 01 §2.6, 02 §4.2 | Medido por el propio proyecto. |
| **3** | **El operador de suavidad es de cuarto orden, no de segundo.** Se penaliza $\|Lm\|^2=m^\top L^2m$ con $L$ un Laplaciano de grafo, mientras la referencia citada (Li & Oldenburg 1998) usa primeras diferencias. | 01 §2.7 | Discrepancia cita-vs-código. Nunca medida. |
| **4** | **Una condición de contorno de Dirichlet que nadie eligió.** Restringir el Laplaciano al dominio activo por indexado deja filas que no suman cero, imponiendo contraste nulo en el aire y en el borde podado. | 01 §2.7c, 02 §2.4 | Hallazgo de esta auditoría. No documentado en el código. |
| **5** | **`cond_A` no es el número de condición**, sino una cota inferior ($\max\|a_j\|/\min\|a_j\|$) que puede ser arbitrariamente mala justo cuando las columnas son casi colineales — la situación normal aquí. Se usa como disparador de salvaguardas. | 02 §6 | Verificado. |
| **6** | **Una constante que contradice su propia justificación.** `PRECONDITIONED_OPERATING_LAMBDA = 0.1` mientras el comentario que la explica valida $\lambda\approx3$ y declara óptimo el rango $O(1\text{–}10)$. | 01 §3.3 | NO DETERMINADO cuál de los dos está desactualizado. |
| **7** | **El truncamiento del kernel a 800 m no tiene cota de error** en ninguna parte del repositorio. | 03 §3.3, 02 §2.2 | NO DETERMINADO. |
| **8** | **Una función de despacho testeada que producción no ejecuta.** `select_solver` tiene cinco tests; el despacho real está escrito en línea en otro archivo. Hoy son equivalentes, pero la suite no protege el camino real. | 02 §4.1 | Verificado por búsqueda exhaustiva. |
| **9** | **Un test tautológico congeló la física del hallazgo 0.** `test_tc_matches_pointmass_formula` reimplementa la misma fórmula en el test y la compara consigo misma con `rtol=1e-9`. El proyecto ya había auditado esa función: detectó que **el nombre** mentía y corrigió el nombre, sin preguntar si la fórmula era correcta. | 12 §5.2 | Verificado. |
| **10** | **Una semilla no es una muestra.** El propio proyecto midió que 1 de cada 3 realizaciones de ruido da 169 m de error en vez de 19 m **con diagnósticos idénticos**; los tests y benchmarks usan semilla fija. La métrica de calidad publicada no discrimina entre un resultado bueno y uno diez veces peor. | 12 §4.4, §10 P3 | Medido por el proyecto. |
| **11** | **El veredicto puede mejorar cuando se mide menos.** El tope a MEDIUM se aplica si el checkerboard **falla**, pero `NOT_RUN` no tiene efecto. | 12 §7.5 | Verificado. Frecuencia real en producción NO DETERMINADA. |
| **12** | **`bulk_rock_mass_kg` está en toneladas** — factor 1.000 entre el nombre de la columna y su valor (volumen m³ × densidad t/m³). Se escribe en cada corrida; sin consumidor identificado. | 06 §5.1 | Verificado. |
| **13** | **`density_contrast` de la exportación se calcula contra un literal `2.6`** en vez de contra `base_density`, que es configurable. Columna homónima pero distinta de la que consume el frontend (`density_contrast_t_m3`, correcta). | 06 §5.1 | Verificado. |
| **1b** | **Vóxeles e isosuperficies parecen no compartir el eje vertical.** Los vóxeles llevan `y` cruda a Three.js (donde +Y es arriba), así que la profundidad crece **hacia arriba**; las isosuperficies llegan del backend ya con `vy = cy − y_m` y se montan bajo el mismo grupo, que vuelve a restar el centro. Resultado: especulares y doblemente centradas. Dos comentarios del código afirman «superposición exacta», y el modo fantasma depende de ella. | 09 §4 | Derivado de 4 archivos. **Sin verificación visual** — comprobable en 30 s abriendo la app. |
| **2b** | **La escala de color y el umbral de visibilidad son relativos a cada corrida.** El fondo es la mediana y la escala la dispersión robusta de ese modelo; se ocultan las celdas bajo el 20 % del pico. Consecuencia: **siempre se ve un cuerpo compacto**, haya o no anomalía significativa, y dos modelos no son comparables a simple vista. | 10 §3, §4.1 | Verificado. |
| **1c** | **El bundle ZIP escribe UBC-GIF sin permutar los ejes.** Hay dos escritores del mismo formato: el de disco transpone, permuta los conteos e invierte el eje vertical; el del ZIP escribe `nx ny nz` tal cual, con origen `0 0 0`. Para un modelo 20×10×20 las cabeceras salen `20 20 10` y `20 10 20`. Afecta también al orden del `.mod` y a las coordenadas del `.gslib`. El ZIP es el **artefacto de entrega industrial**. Invisible con malla cúbica. | 11 §4 | **Verificado** por lectura de ambas rutas completas. |
| **14** | **Sección económica del reporte sin productores.** Siete tarjetas (NPV, LOM, cutoff, ore/waste tonnage…) que ningún módulo calcula; siempre renderizan "No disponible". Degrada bien, pero sugiere una capacidad inexistente. | 06 §7.2 | Verificado por búsqueda exhaustiva. |

### Lo que esta auditoría considera ejemplar

Un expediente que sólo lista defectos calibraría mal al revisor. Estas prácticas son
mejores que las habituales en software científico y merecen mencionarse:

- **Los diagnósticos de honestidad del prior geológico** (informe 05 §3.6). El sistema no
  se limita a aplicar el prior: mide y **declara** cuándo es exactamente inerte
  ($L\cdot\text{cte}=0$), cuándo el campo implícito degeneró a un plano extrapolado, hasta
  qué distancia del sondaje más cercano está afirmando geología, y que un parámetro que el
  usuario cree que actúa (`declared_std_is_inert`) en realidad no se consume.
- **Elegir el término de acople midiendo, con control negativo** (informe 05 §3.5). El
  prior geológico se probó por dos vías y se eligió la que mejora; el control con
  **geología falsa** resultó el peor brazo, que es la firma de una restricción que
  transporta información real y no sólo regulariza.
- **El veredicto por eslabón más débil** (informe 12 §7.1): tomar deliberadamente el peor
  de los indicadores y declararlo como método.
- **Desacoplar la confianza en profundidad** y fijarla en `LOW` por defecto (informe 04
  §8.1), tras medir que gravedad-sola no resuelve profundidad absoluta.
- **Negarse a usar $\chi^2$ cuando $\chi^2$ no es interpretable** (informe 12 §6.1).
- **Publicar `istop`** del solver, es decir, declarar cuándo el solver «se rindió» en lugar
  de presentar el resultado como convergido (informe 02 §4.2).
- **Identidad byte a byte** en refactorizaciones numéricas, reconociendo que la
  reasociación en coma flotante no es neutra (informe 12 §2.3).
- **Errores que preguntan** en marea y deriva: en vez de rellenar con un valor por
  defecto, el sistema rechaza y nombra la estación base candidata (informe 04 §4.1).

---

## 8. Agradecimiento y disposición

Cualquier corrección, por dura que sea, es bienvenida y será registrada con
atribución en el expediente. Si un informe contiene un error conceptual, la
respuesta correcta del proyecto no es defenderlo: es medirlo y corregirlo.

---

*Documento vivo. Se actualiza a medida que avanza la auditoría del código.*
