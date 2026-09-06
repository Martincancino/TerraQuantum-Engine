# TerraQuantum — AUDITORÍA TÉCNICA INTEGRAL

| Campo | Valor |
|---|---|
| Fecha | 2026-08-04 |
| Encargo | Auditoría de nivel CTO pre-inversión: todo el proyecto contra los 13 informes Deep Research de `Documentos/diseño` |
| Alcance medido | Backend 109.506 LOC Python (116 archivos por AST, 1.012 funciones, 32.091 ventanas comparadas) · Frontend 28.327 LOC TS/TSX · 60 endpoints · 44 variables de entorno · 32 dependencias · **14 informes, 79.324 palabras** (el 14º se añadió al corpus durante la auditoría) |
| Naturaleza | Documento de diagnóstico. **No se modificó una sola línea de código de producción durante esta auditoría.** |
| Pasadas | **1ª** (§1–§9): lectura del núcleo numérico + verificación numérica → H-1…H-8. **2ª** (§9-BIS): estudios instrumentados sobre el 100% del repositorio → H-9…H-16. **3ª** (§9-TER): empaque y calidad real de los tests → H-17…H-24. **4ª–5ª** (§9-QUATER): verificación de suposiciones propias contra el orquestador → H-26, H-27, y **2 autocorrecciones**. **6ª** (§9-QUINQUIES): lógica del frontend → H-28…H-32. **7ª** (§9-SEXIES): informe 04 y comprar-vs-construir → Fase 11. **8ª** (§9-SEPTIES): motor magnético → H-33 y **3ª autocorrección**. **9ª** (§9-OCTIES): UX y anti-scope (informes 03, 07, 12) → H-34. **10ª** (§9-NONIES): informe 14 nuevo, arquitectura de escala industrial → H-35, H-36. **11ª** (§9-DECIES): solvers magnéticos secundarios → H-37…H-39. |
| Hallazgos | **39**, de los cuales **4 críticos** y 23 altos, más **3 autocorrecciones**. Todos los críticos y los de mayor consecuencia fueron verificados personalmente por el auditor —numéricamente cuando el hallazgo lo permitía—, no solo reportados. |

---

# 0. CÓMO LEER ESTE DOCUMENTO (y qué confianza darle a cada afirmación)

Cada afirmación está etiquetada:

- **[MEDIDO]** — lo verifiqué ejecutando código o análisis estático durante la auditoría. Incluyo el número.
- **[HECHO]** — lo leí directamente en el código, con `archivo:línea`.
- **[INFERENCIA]** — deducción razonable a partir de lo anterior. Puede estar equivocada.
- **[OPINIÓN]** — juicio de ingeniería. Discutible por definición.

Esta distinción no es decorativa: es la misma disciplina que el propio proyecto se impuso en `docs/05_RIGOR_FISICO_Y_RED_TEAM.md` ("nunca creerle al motor sin oráculo"), y sería incoherente auditarlo con menos rigor del que él se exige.

## 0.1 Limitaciones honestas de esta auditoría

1. **El informe 06 está truncado en origen.** `Diseño Arquitectónico de Software CAD 3D y Modelamiento Científico.docx` contiene **57 palabras** — solo su párrafo final. Su `word/document.xml` pesa 4,4 KB frente a los 40–100 KB de los demás. No se perdió en la extracción: el archivo fuente está incompleto. Lo poco recuperable (síntesis híbrida CGAL + OCAF + CoW Depsgraph + VTK) se integró al análisis del informe 05. **Recomendación: regenerar ese informe.**
2. **No leí las 137.000 líneas una por una.** Leí íntegramente el núcleo numérico crítico (`solve_inversion_lsqr` completa, la cadena de pesos, el bucle IRLS, el ensamblado), analicé por AST el 100% del backend, y usé consultas estructurales dirigidas para el resto. Donde no tengo evidencia directa lo digo.
3. **La delegación en subagentes falló a mitad del trabajo** por el límite de gasto de la cuenta (26 de 32 agentes murieron). Los mapas de los informes 01–11 sobrevivieron; los mapas de código no. **Consecuencia: la auditoría de código la hice yo directamente**, lo cual es mejor para el juicio pero limitó la exhaustividad línea a línea en frontend, tests y empaque. Las secciones afectadas están marcadas con *cobertura parcial*.
4. **No ejecuté la suite de tests completa** (25+ min y coste). Las afirmaciones sobre testing se basan en configuración, marcadores y estructura, no en una corrida.

---

# 1. RESUMEN EJECUTIVO — EL VEREDICTO

## 1.1 La respuesta en un párrafo

TerraQuantum es **un producto científico real, no un prototipo**. Tiene un motor de inversión geofísica con formulación matemática defendible frente a la literatura (Li & Oldenburg, Last & Kubik, Portniaguine & Zhdanov), validado contra cuatro benchmarks externos con números publicables, y una capa de ingesta de datos sucios que es genuinamente su mejor activo de ingeniería. También tiene una disciplina de honestidad epistémica —medir antes de prometer, documentar los límites físicos como leyes y no como bugs— que **no he visto en la mayoría del software comercial del sector** y que constituye su foso competitivo real. Contra eso: el camino crítico del producto vive en dos funciones de ~3.000 líneas combinadas con complejidad ciclomática de 201 y 137, la arquitectura es de acreción por fases (cada feature añadió una rama guardada dentro del monolito en lugar de una pieza componible), y hay un defecto numérico verificado que explica semanas de experimentos fallidos que el equipo ya había medido empíricamente sin encontrar su causa.

## 1.2 Si yo tuviera que decidir la inversión

**Invertiría, con condiciones.** El activo no es el código: es **el motor validado + la ingesta blindada + la cultura de medición**. El código del camino crítico es refactorizable; la validación física y la disciplina no se compran.

Las cuatro condiciones serían:

1. **Arreglar el arranque del instalador** (H-17/H-18, §9C.1-2). *Añadido tras la 3ª pasada, y es el más urgente en términos comerciales.* Si un sidecar no levanta —antivirus, puerto ocupado, DLL faltante— el cliente ve **un splash de carga infinito, sin mensaje, sin reintento y sin logs**. Y si lo mata desde el Administrador de Tareas, quedan procesos huérfanos que impiden el siguiente arranque. **Un producto que no puede decir "no arrancé" no se puede vender a un tercero**, por bueno que sea su motor.
2. **Cerrar el hallazgo H-1** (el depth-weighting inerte, §6.2). El `W_z` de gravimetría es algebraicamente inerte y el peso de modelo efectivo es la norma de columna del kernel, no lo que el código dice implementar. Hasta saber si repararlo cambia la recuperación de profundidad, no se sabe qué producto se tiene. *(Nota: una hipótesis más alarmante sobre el selector de λ fue investigada y **descartada** — ver la corrección en §9D.2.)*
3. **Partir la espina dorsal** (§2.3, H-3, H-9). Con 1.996 líneas y CC=201 en una función, y 228 ventanas duplicadas entre los dos motores, el coste marginal de cada feature crece de forma no lineal y el riesgo de regresión silenciosa es estructural.
4. **Que la CI ejecute de verdad la regresión física, y que los gates decidan** (H-4, H-22). Hoy la suite que "congela la física para siempre" está desactivada por defecto y la CI no la activa; y 43 de 65 scripts de validación no tienen criterio automático de PASS/FALLO.

**El patrón estructural de este proyecto — y la conclusión más útil de toda la auditoría.** Encontré **cinco** veces la misma forma, en cinco subsistemas sin relación entre sí: **entre lo que el sistema declara y lo que el sistema hace, se abre un hueco que nadie comprueba.**

| # | El backend hace lo correcto… | …y el usuario nunca lo ve |
|---|---|---|
| H-10 | Licenciamiento, diagnóstico y conectividad, con gate 30/30 | Ningún componente llama a esos 5 endpoints |
| H-20 | Updater configurado, firmado, `.sig` producidos | Ninguna línea de código invoca la comprobación |
| H-17 | El error de arranque se captura y se registra | Splash infinito, sin mensaje |
| **H-27** | **La caída a topografía plana se registra con motivo nombrado** | **0 lecturas en el frontend; el modelo sale con sello de bueno** |
| **H-37** | **El modo `amplitude` está declarado en el esquema, ofrecido en la UI y con su solver implementado y testeado** | **Ninguna rama lo despacha: corre TMI inducida y el reporte dice "amplitude"** |

No es descuido repetido: es que **los criterios de cierre miden que la pieza exista, no que el camino esté conectado**. Un gate que dice "el endpoint responde" se lee como "la función existe"; un `Literal` en un esquema Pydantic se lee como "el modo funciona".

**H-37 es la forma más grave del patrón**, porque el hueco no queda en silencio: **el sistema afirma activamente haber hecho algo que no hizo.** Los demás omiten; éste miente.

**Corregir la plantilla de gate —exigir en cada fase un criterio "un usuario puede hacer/ver X desde la UI" y un test que recorra todos los valores de cada enumerado— vale más a largo plazo que corregir los cinco hallazgos por separado**, porque impide el sexto.

Y tiene una implicación incómoda que conviene decir: la honestidad epistémica es el diferenciador declarado del producto (§1.1). H-27 muestra que **esa honestidad está implementada en la frontera del backend y no cruza al usuario**, que es justo donde el diferenciador tendría que notarse.

## 1.3 Los 39 hallazgos, re-medidos uno a uno

> **Re-medición completa — FASE 29, 2026-09-06.** Esta tabla se escribió el
> 2026-08-04 y durante trece meses de trabajo **nunca se volvió a contrastar con el
> código**: era el hueco que el propio plan §1 de `docs/10_PLAN_FASES_15_26.md`
> declaraba («las auditorías se escribieron *antes* que las fases y nunca se
> re-midieron»). La Fase 29 la re-mide. Reglas de esta re-medición, para que se
> pueda auditar a su vez:
>
> 1. **Cada fila lleva fecha y `ruta:línea`.** Una fila sin evidencia no cuenta como
>    verificada y se marca **NO RE-MEDIDO** en vez de heredar su estado anterior.
> 2. **`ruta:línea` es de hoy, no del 04-ago.** Varias referencias del expediente
>    académico habían derivado: la que él cita como `gravimetry.py:2233-2235` es hoy
>    `gravimetry.py:2246-2247`. Se citan las de hoy.
> 3. **Donde el defecto sigue vivo se dice vivo**, aunque la fase que lo tocaba esté
>    cerrada. Cerrar una fase y cerrar un hallazgo no son lo mismo.
> 4. **El título antiguo decía «Los 8 hallazgos que importan» y la tabla tenía 39
>    filas.** Se corrige el título en vez de recortar la tabla.
>
> **Marcadores:** ✅ CERRADO · 🟡 PARCIAL (mitigado, con un resto medido) ·
> 🔴 VIVO · ⬜ NO RE-MEDIDO.
>
> **Cierre del gate de la Fase 29, medido sobre esta misma tabla.** De las **41** filas:
> **36** llevan `ruta:línea`; **3** (H-6, H-7 y H-31) tienen por evidencia una **AUSENCIA**
> —un fichero borrado no tiene número de línea, así que se declara como lo que es, y se dice
> además que ningún guard la sostiene—; y **2** son autocorrecciones del propio auditor, cuya
> evidencia correcta es la sección de este informe donde se argumentan, no una coordenada de
> código. Ninguna fila hereda su estado de 2026-08-04 sin volver a mirarlo.

| # | Hallazgo | Sev. original | Estado 2026-09-06 | Evidencia (`ruta:línea`) |
|---|---|---|---|---|
| **H-1** | `W_z` se cancela contra `Ws`; `depth_beta` inerte | 🔴 Crítico | ✅ **CERRADO** (Fase 4, 08-14). `depth_beta` fuera de la firma del solver de malla regular; **vivo y declarado** en el solver Octree, que es otro funcional. Mutación de la F29: re-añadirlo a la firma → gate **rojo** | `exploration/gravimetry.py:3157-3162` (lápida) · `exploration/gravimetry.py:3926` (Octree, vivo) · `tests/test_fase4_depth_weighting.py:204` |
| **H-2** | `solve_sparse_normal_equations` se invoca y no existe | 🟠 Alto | ✅ **CERRADO** (Fase 6). **0** apariciones en código de producción. Mutación: reintroducir la llamada → gate **rojo** | `tests/test_fase6_limpieza_verificada.py:45` |
| **H-3** | 21 funciones concentran el 26,4 % del código; `run_geophysics_inversion` 1.996 LOC / CC 201 | 🟠 Alto | 🔴 **VIVO, desplazado.** Las dos funciones que la ficha nombra sí se partieron (Fase 8). Pero el **criterio de aceptación de esa fase —LOC ≤ 300, CC ≤ 40, args ≤ 12— no se cumple hoy**: 8 funciones superan 300 LOC, la CC máxima es **181** y la firma más ancha, **39** argumentos. Y `ast_budgets.py` **no vigila el criterio**: vigila NO-REGRESIÓN contra un baseline que **codifica las violaciones como suelo aceptado**. Concentración re-medida: las 21 funciones más largas = **13,7 %** de 56.714 LOC de producción (122 ficheros, 1.121 funciones) | `scripts/ci/ast_baseline.json` · `services/gravity_import_service.py:942` (CC **181**, 777 LOC) · `exploration/magnetometry.py:838` (812 LOC, 37 args) · `services/joint_inversion.py:548` (812 LOC) · `exploration/gravimetry.py:3077` (**39** args) |
| **H-4** | La regresión física F9 no corre en CI | 🟠 Alto | ✅ **CERRADO** (Fase 3). Canario en cada PR + job nocturno completo | `.github/workflows/ci.yml:96` (canario en cada PR) · `:210` (job nocturno completo) |
| **H-5** | La CI compila dos directorios inexistentes y pasa igual | 🟡 Medio | ✅ **CERRADO**. Mutación: error de sintaxis en producción → gate **rojo** | `scripts/ci/compile_check.py:84-106` (contrasta declarados contra disco y sale ≠ 0) |
| **H-6** | Código muerto en el frontend (~30 KB) | 🟡 Medio | ✅ **CERRADO** (Fase 6). `reactiveUpdateGraph.ts`, `engine-physics.ts` e `InstancedSegmentsLayer`: **0 ficheros, 0 referencias** | **ausencia**, medida 2026-09-06: 0 ficheros y 0 referencias a `InstancedSegmentsLayer` en `terraquantum-web/{lib,componentes}`. *Un fichero borrado no tiene número de línea: la coordenada es la ausencia — y no hay guard que la sostenga* |
| **H-7** | Clave RSA revocada committeada | 🟡 Medio | 🟡 **PARCIAL.** **0** ficheros `credenciales_gee.json*` en el árbol de trabajo. **La historia de git NO se re-midió** en esta fase: sigue siendo cierto que la clave estuvo committeada y una purga de historia es una decisión con coste (reescribe 189+ commits) que no toma una auditoría | **ausencia** en el árbol, medida 2026-09-06 (`rglob('credenciales_gee.json*')` → 0). Historia de git: **⬜ NO RE-MEDIDA** |
| **H-8** | Ausencia del dominio minero económico | 🟢 Info | ✅ **DECLARADO** anti-scope permanente | `docs/10_PLAN_FASES_15_26.md:2870` («No implementar la sección económica») |
| **H-9** | 228 ventanas duplicadas entre los dos motores | 🟠 Alto | 🟡 **CERRADO EN SU PAR, CIEGO EN LOS DEMÁS.** El par gravimetría↔magnetometría está en **20** (criterio < 40) y la mutación lo caza. **Pero el gate vigila UN par y los tres peores de hoy son otros**: `gravimetry ↔ geophysics_service` **72**, `gravity_import_api ↔ gravimetry` **67**, `gravity_import_api ↔ geophysics_service` **64**; y la auto-duplicación de `api/gravity_import_api.py` consigo mismo (**102** ventanas) no la mira nadie —el baseline la guarda **vacía**—. Segundo límite, **medido por mutación**: el gate cuenta **huellas ÚNICAS**, así que re-duplicar un bloque *ya* compartido es invisible (la primera mutación de la F29 escapó exactamente por eso; la segunda, con código no compartido, lo puso rojo) | `scripts/ci/study_duplication.py:158-175` · `scripts/ci/duplication_baseline.json` (`"propio": {}`) |
| **H-10** | La fase F7 completa no tiene UI: 5 endpoints sin consumidor | 🟠 Alto | ✅ **CERRADO** (Fase 9). Mutación: proxy de Next sin llamador → gate **rojo**. Deuda declarada: **9** rutas y **1** proxy tolerados | `tests/test_fase9_camino_de_usuario.py:42` (9 rutas) · `:94` (1 proxy) |
| **H-11** | 29 de 44 variables de entorno nunca se ejercitan | 🟡 Medio | ✅ **CERRADO** (Fase 5). Mutación: variable nueva sin declarar → gate **rojo** | `tests/test_fase5_superficie_config.py:318` (el censo cubre todo el backend) · `:338` (ninguna variable sin ejercicio) |
| **H-12** | `core/storage.py` huérfano | 🟡 Medio | ✅ **CERRADO**. No existe | **ausencia**: `core/storage.py` no existe, y lo sostiene `tests/test_fase6_limpieza_verificada.py:89`. `core/` = 11 ficheros, 1.881 LOC |
| **H-13** | 16 símbolos públicos sin referencia | 🟡 Medio | ✅ **CERRADO** con guard vivo. `HUERFANOS_TOLERADOS` = **4**, cada uno con motivo escrito. El guard **se excluye a sí mismo del barrido**, con la justificación medida — es decir, la patología de auto-satisfacción que la F29 busca **aquí ya está resuelta** | `tests/test_fase6_limpieza_verificada.py:417-431` |
| **H-14** | `distributed` y `shapely` declaradas y no importadas | 🟢 Bajo | ✅ **CERRADO** (Fase 6). Sólo quedan las lápidas en comentarios | `terraquantum-backend/requirements.txt:17,30,72` |
| **H-15** | El backend escucha en `0.0.0.0` por defecto | 🟡 Medio | ✅ **CERRADO** (Fase 2). Default **loopback** + aviso ruidoso al arrancar si se expone sin auth | `core/config.py:152` · `main.py:126-134` |
| **H-16** | El frontend concentra más complejidad que el backend; `PrepPanel` con 41 `useState` | 🟠 Alto | 🟡 **PARCIAL.** La mitad de `useState` está **cerrada**: el máximo hoy es **10** (`BoreholeUploadPanel.tsx`), bajo el techo de 12, y la mutación lo caza. La mitad de concentración **mejoró y no se cerró**: los 8 ficheros mayores son el **34,1 %** (era 40,2 %), pero el frontend creció de 28.327 a **37.366 LOC** y `PrepPanel.tsx` sigue en **2.222** y `Scene3D.tsx` en **2.099** | `tests/test_fase10_contratos.py:474` (techo 12) · `componentes/PrepPanel.tsx` · `componentes/Scene3D.tsx` |
| **H-17** | Sidecar que no arranca ⇒ splash infinito | 🔴 Crítico | ✅ **CERRADO** (Fase 2) **y desde la Fase 28 su puerta EXISTE**: los tests de Rust los corre el job `desktop-shell` y `check.ps1` | `terraquantum-web/src-tauri/src/lib.rs:1262` (módulo de tests, **19** `#[test]`) · `:1360` (todo error de arranque habla español) · `.github/workflows/ci.yml:170` (job `desktop-shell`) · `check.ps1:43` (paso 1b) |
| **H-18** | Sin Job Object: procesos huérfanos | 🔴 Crítico | ✅ **CERRADO** (Fase 2), misma puerta que H-17 | `terraquantum-web/src-tauri/src/lib.rs:1262` (misma puerta que H-17: `cargo test --lib`, **19/19 verde** el 2026-09-06) |
| **H-19** | `wait_for_port` acepta cualquier listener | 🟠 Alto | ✅ **CERRADO** (Fase 2): identidad por token, misma puerta | `core/config.py:158` (`INSTANCE_TOKEN`) · `src-tauri/src/lib.rs` |
| ~~**H-20**~~ | Updater firmado que nadie invoca | 🟠 Alto | ✅ **CERRADO** en dos tiempos (Fase 2 + Fase 28). Riesgo abierto **NUEVO-13**: mientras el repo sea privado el updater dará 404 aunque se publique | `src-tauri/tauri.conf.json:34` · `src-tauri/src/lib.rs:952-1010` · `docs/04` §6.1 |
| **H-21** | El navegador llama directo al backend en 3 puntos | 🟠 Alto | ✅ **CERRADO** (Fase 2). Guard estático **verde hoy**: «ninguna llamada directa navegador→backend» | `terraquantum-web/scripts/check_client_backend_calls.mjs` · `.github/workflows/ci.yml:149` (el paso que lo corre). Ejecutado a mano el 2026-09-06: exit 0 |
| **H-22** | 43 de 65 scripts de `validation/` no deciden nada | 🟠 Alto | ✅ **CERRADO** (Fase 3). Mutación: script nuevo sin clasificar → gate **rojo** | `scripts/ci/validation_inventory.py:220` (sale 1 si algo queda sin clasificar) · `scripts/validation/GATES.json` (73 scripts: 24 gates, 39 diagnósticos, 3 bibliotecas, 7 colecciones) |
| **H-23** | Reproducibilidad parcial: sin lockfile ni versión de Python | 🟡 Medio | ✅ **CERRADO** (Fase 27): `requirements.lock` con hashes e instalación `--require-hashes` en los dos jobs. **Resto medido por la F29:** `check.ps1` invoca `python`, que en la máquina de desarrollo es **3.11.9 sin numpy ni pytest**, mientras la CI lee `.python-version` (**3.14.4**). La puerta local y la puerta remota **no validan con el mismo intérprete** | `terraquantum-backend/requirements.lock` · `.github/workflows/ci.yml` · `check.ps1:12,16,19,22,68` (`python`) vs `terraquantum-backend/.python-version` |
| **H-24** | El ZIP de diagnóstico puede filtrar datos vía tracebacks | 🟡 Medio | 🔴 **VIVO tal como se describió.** La config **sí** se sanea, pero `recent_errors.json` guarda **la cola literal del traceback** (últimos 2.000 caracteres) y viaja al ZIP sin filtro. El docstring promete «JAMÁS guarda datos de survey» y lo que garantiza es que no guarda el **body**: el **mensaje** de una excepción sí puede llevar valores de celda | `core/diagnostics_buffer.py:24-34` · `services/diagnostics_service.py:106,109,152` |
| **H-25** | Dos selectores de λ obsoletos siguen invocables | 🟡 Medio | 🟡 **MITIGADO Y DECLARADO.** `select_lambda_lcurve` sigue existiendo, con **0 llamadores de producción**, y hay un test que lo fija. Lo usan un arnés de byte-identidad y un script de `tests/` que **pytest no colecta** (0 tests) | `exploration/gravimetry.py:1416` · `api/geophysics_api.py:238,250` · `tests/test_fase1_literal_dispatch.py:225` |
| **H-26** | Cuatro definiciones del término de modelo sin prueba que las compare | 🟠 Alto | ⬜ **NO RE-MEDIDO** por la Fase 29. Sigue sin dueño en el plan; lo más cercano es el arnés de byte-identidad de la Fase 7, que congela cada ruta contra sí misma pero **no las compara entre sí** | Las cuatro conviven en `exploration/gravimetry.py:1416` (L-curve), `:1674` (χ² objetivo), `:3077` (solver de producción) y `exploration/magnetometry.py:838` (motor magnético). `scripts/validation/fase7_byte_identity.py` congela cada una **contra sí misma**; ninguna prueba las compara **entre sí** |
| **H-27** | La inversión puede caer a topografía PLANA sin avisar | 🟠 Alto | ✅ **CERRADO.** El aviso se emite (`topography_run_warnings`), viaja en `warnings[]` de la respuesta y el visor lo **lee y lo muestra** | `services/geophysics_service.py:330-338,2962-2964` · `componentes/views/Exploration3DView.tsx:139,451-453` · `lib/terraquantum/runWarnings` |
| **H-28** | El modelo 3D del survey anterior sobrevive al cambio de CSV | 🟠 Alto | ✅ **CERRADO** (Fase 1). `resetExplorationState` desapareció y su trabajo vive en el store | `store/useAppStore.ts:555` · `componentes/views/Exploration3DView.tsx:357` |
| **H-29** | El reconocimiento de riesgo espacial sobrevive al cambio de archivo | 🟠 Alto | 🟡 **CERRADO, CON LA PUERTA MUERTA.** El arreglo está y está comentado; su gate de aceptación es un recorrido de Playwright que **no ejecuta ninguna puerta** (ver §1.4) | `componentes/PrepPanel.tsx:690,1176` · gate: `terraquantum-web/e2e/fase1_confianza.spec.ts` (**no lo corre nadie**) |
| **H-30** | El frontend deriva el contraste con roca país fija de 2,75 t/m³ | 🟠 Alto | 🔴 **VIVO, y en dos sitios.** La constante `DENSITY_COUNTRY_ROCK_FALLBACK_T_M3 = 2.75` sigue decidiendo qué vóxeles se ven cuando el backend no manda el campo | `componentes/Scene3D.tsx:93` · `lib/terraQuantumGeology.ts:143` |
| **H-31** | `geophysicsModel.ts` fabrica coordenadas lat/lon | 🟡 Medio | ✅ **CERRADO**. El fichero no existe | **ausencia**: `terraquantum-web/lib/geophysicsModel.ts` no existe (medido 2026-09-06). Sin guard que lo sostenga |
| **H-32** | Un `catch` con sólo `console.warn` deja al usuario sin señal | 🟡 Medio | ⬜ **NO RE-MEDIDO en su sitio original.** Lo que hay hoy en `Scene3D.tsx` son dos `console.warn` de **textura de terreno** (degradación cosmética con material de reserva), que no es el caso que la ficha describe (recarga de modo/LOD del modelo) | `componentes/Scene3D.tsx:1199,1204` |
| **H-33** | En magnetometría `depth_beta` actúa o no según el padding | 🟠 Alto | 🟡 **VIVO Y DECLARADO.** El parámetro sigue en la firma del solver magnético, y desde la Fase 7 **la corrida declara en su salida** qué funcional usó — que era el criterio (d) de aquella fase, no la eliminación del parámetro | `exploration/magnetometry.py:887` (firma) · `:1590` (`solver_meta["depth_beta"]`) · `:1592` (nota de H-33) |
| **H-34** | Colormap arcoíris (Turbo) vivo en susceptibilidad | 🟡 Medio | 🟡 **EL RENDER SE ARREGLÓ; LA ETIQUETA NO.** El visor pinta **Plasma** desde la Fase 1; el panel de control sigue diciéndole al usuario **«Turbo · log₁₀(χ + ε)»**. **No es un hallazgo nuevo de la F29**: ya está anotado en `docs/ARQUITECTURA.md` §10 *Frontend* con estas palabras — «Turbo en leyenda de `MultiPhysicsControls` describe colores que ya no se pintan». Lo que la F29 aporta es la coordenada exacta y que **sigue ahí** | `lib/terraQuantumGeology.ts:180-191` (Plasma) vs `componentes/viewport/MultiPhysicsControls.tsx:32` (dice «Turbo») |
| **H-35** | El 41 % del `core/` es dominio, no infraestructura | 🟠 Alto | ✅ **CERRADO** (Fase 6). `block_model_store.py`, `geo_utils.py` y `gee_client.py` viven en `services/`; `core/` son **11 ficheros y 1.881 LOC** de infraestructura | `services/block_model_store.py` · `services/geo_utils.py` · `services/gee_client.py` · `tests/test_fase6_limpieza_verificada.py:280` |
| **H-36** | No existe la noción de «dato evaluado» con procedencia y validez | 🟠 Alto | 🟡 **CERRADO EN SU MITAD ÚTIL** (Fase 25, 09-03). Existe el tipo exhaustivo que obliga a clasificar **cada** parámetro de preparación como invalidante o `NO_DESHACIBLE` —un campo sin clasificar **no compila**—, con **34** parámetros declarados. Lo que sigue sin existir es el recómputo **incremental**, y no tiene fase dueña | `terraquantum-web/componentes/prep/invalidaResultado.ts:28,48,77-127` (22 KB) |
| **H-37** | La UI ofrece un modo (`amplitude`) que el motor nunca ejecuta | 🔴 Crítico | ✅ **CERRADO** (Fase 1). El modo se **rechaza antes de computar**, con causa y alternativa. Mutación: anular el rechazo → gate **rojo** | `services/geophysics_service.py:551-576` · `:2698-2704` · `tests/test_fase1_literal_dispatch.py` |
| **H-38** | El padding es incondicional en producción ⇒ `depth_beta` inerte en los tres solvers | 🟠 Alto | 🔴 **VIVO por diseño, y ahora con una consecuencia medida.** La producción sigue pasando `padding_mask` siempre. La Fase 29 mide el efecto colateral que nadie había contado: **el padding crea celdas de aire**, y con ellas la frontera implícita de ACAD-4 — en una corrida real de `run_geophysics_inversion` son **2.000 de 7.200 celdas (27,8 %)** | `services/geophysics_service.py:2772,2800,3549` · medición: `tests/test_doi_calibration.py` corriendo con log INFO, 2026-09-06 |
| **H-39** | Los kernels de MVI y tensor ignoran `near_field_mode='prism'` | 🟠 Alto | 🔴 **VIVO, sin cambios.** `build_mvi_kernels` y `build_gradient_tensor_kernels` contienen **cero** referencias a `near_field_mode` y **cero** menciones de `prism`: siempre dipolo | `exploration/magnetometry.py:519` · `:629` (verificado por AST, 2026-09-06) |
| **(corrección 1)** | H-1 no afecta a magnetometría por el mecanismo de `Ws` | — | ✅ Se mantiene; ver H-33 | `docs/06` §9D.1, §9G.1 |
| **(corrección 2)** | H-25 rebajado de Crítico a Medio | — | ✅ Se mantiene; ver H-25 | `docs/06` §9D.2 |

## 1.4 Los gates: primero ¿corren?, después ¿defienden? (FASE 29, 2026-09-06)

La 4ª pregunta del gate de este proyecto es *«¿falla el gate si se rompe lo que dice
defender?»*. La Fase 28 añadió una pregunta **anterior** y más barata, y la añadió
porque le costó 26 días descubrirla: **¿lo ejecuta alguien?** Nueve tests de Rust
escritos como puerta no los corría ni la CI ni `check.ps1`. Esta sección responde las
dos, para las 14 fases del plan §10, y la primera respuesta es peor que la de la
Fase 28.

### 1.4.1 Censo de puertas muertas — **152 pruebas escritas como gate que no ejecuta nadie**

| Puerta | Pruebas | Quién la ejecuta | Evidencia |
|---|---:|---|---|
| `terraquantum-backend/scripts/validation/test_*.py` (20 ficheros) | **56** | **NADIE** | `pytest.ini:2` las declara en `testpaths`, pero **todos** los pasos de CI y de `check.ps1` invocan `pytest tests/…`, que nunca pasa por ese directorio |
| `terraquantum-web/e2e/*.spec.ts` (8 specs) | **57** | **NADIE** | `.github/workflows/ci.yml` no menciona `playwright` ni `test:e2e` en ningún job; `check.ps1` tampoco. El runner existe (`scripts/e2e_ui.ps1`) y hay que lanzarlo a mano |
| Tests `slow` sin paso propio (7 ficheros) | **39** | **NADIE** | el paso «Suite de tests» corre `pytest tests/ -m "not slow"`; ningún otro paso los nombra |
| **TOTAL** | **152** | | |

Los 39 `slow` huérfanos, uno a uno: `test_f8_e2e_matrix.py` (**21**),
`test_fase11_api_scripting.py` (**11**), `test_f8_soak.py` (2),
`test_fase14_geologia_implicita.py` (2), `test_async_load_package.py` (1),
`test_f8_perf_budgets.py` (1), `test_projected_solver.py` (1).
De los 55 tests `slow` del repositorio, los otros 16 **sí** corren, porque el paso
«Guardas de arquitectura» los invoca **por fichero y sin `-m`**
(`test_fase5_superficie_config.py` 6, `test_fase7_nucleo_compartido.py` 1,
`test_f27_build_guards.py` 1) o porque el nocturno los nombra
(`test_depth_prior_service.py` 2); y de los 6 de `test_f9_physics_regression.py` la CI
corre **uno** por nodeid y declara por escrito que el gate nocturno cubre los otros
cinco «en sustancia».

**Consecuencia directa: los gates de aceptación de las Fases 1, 9, 10, 11, 13 y 14
son, hoy, puertas muertas** — total o parcialmente. La Fase 11 y la Fase 14 no tienen
**ninguna** puerta viva; las Fases 1, 9, 10 y 13 conservan su mitad de backend (que sí
corre y que la Fase 29 verificó por mutación) y han perdido su mitad de recorrido de
usuario.

**Y hay un guard que existía para esto y no lo ve.**
`tests/test_fase3_ci_guards.py:214` (`test_every_validation_test_runs_somewhere`)
comprueba exactamente esta patología… **sólo para el marcador `validation`**, y sólo
dentro de `tests/`. No mira el marcador `slow`, que es por donde se escapan los 39, ni
`scripts/validation/`, que es por donde se escapan los 56, ni Playwright, que es por
donde se escapan los 57. El guard hace lo que dice; lo que dice es más estrecho que el
problema.

### 1.4.2 La puerta pre-push local no puede pasar en la máquina de desarrollo

Esto **ya estaba anotado a medias**: es `NUEVO-12` (Fase 27), que dice que
`deps_closure.py` da falsa alarma con el `python` del PATH. Lo que la Fase 29 añade
es que el problema **no se queda en un falso positivo**: el paso más caro de la
puerta no puede ni arrancar.

`check.ps1` invoca **`python`**. En esta máquina `python` es **3.11.9 sin numpy y sin
pytest**, mientras `terraquantum-backend/.python-version` declara **3.14.4** y la CI lo
lee de ahí. Medido el 2026-09-06:

| Paso de `check.ps1` | con `python` (3.11.9) | con `py -3.14` |
|---|---|---|
| `compile_check.py` | exit 0 | exit 0 |
| `ast_budgets.py` | exit 0 | exit 0 |
| `validation_inventory.py` | exit 0 | exit 0 |
| `deps_closure.py` | **exit 1** (falso positivo: sin metadatos locales no expande 34 distribuciones) | exit 0 (109 distribuciones) |
| `pytest tests/ -q` (`-Tests`) | **imposible**: `No module named pytest` | corre |

O sea: `check.ps1` da **ROJO** por una causa que no es un defecto del código, y su paso
más caro **nunca se ha podido ejecutar aquí**. Es la mitad local de H-23.

### 1.4.3 Verificación por mutación: **15 de 16**

Todas se aplicaron sobre el árbol real, se restauraron y se comprobó la restauración
por **SHA-256 byte a byte** (este repositorio vive en OneDrive y ya tiene documentada
una reversión a media corrida). Arnés y registro completo en el bloque ✅ EJECUTADA de
la Fase 29 en `docs/10_PLAN_FASES_15_26.md`.

| Fase | Qué se rompió | Puerta | Resultado |
|---|---|---|---|
| 3 (H-5) | error de sintaxis en `core/utils.py` | `compile_check.py` | **CAZADA** |
| 3 (H-22) | script nuevo en `validation/` sin ficha en `GATES.json` | `validation_inventory.py` | **CAZADA** |
| 3 (escala) | `G` de 6,67430e-11 a 7,00000e-11 | `test_fase3_calibracion_absoluta.py` | **CAZADA** |
| 4 (H-1) | re-añadir `depth_beta` a la firma del solver | `test_fase4_depth_weighting.py` | **CAZADA** |
| 5 (H-11) | variable de entorno nueva sin declarar | `test_fase5_superficie_config.py` | **CAZADA** |
| 6 (H-2) | reintroducir `solve_sparse_normal_equations` | `test_fase6_limpieza_verificada.py` | **CAZADA** |
| 7 (H-9) | duplicar 155 líneas **ya compartidas** de gravimetría en magnetometría | `study_duplication.py --gate` | **ESCAPA** ← el gate cuenta huellas **únicas** |
| 7 (H-9) | duplicar 155 líneas **no compartidas** | `study_duplication.py --gate` | **CAZADA** |
| 8 | inflar un helper de la espina a CC > 40 | `test_fase8_espina_dorsal.py` | **CAZADA** |
| 8 | función de 200 ramas en `core/` | `ast_budgets.py` | **CAZADA** |
| 9 (H-10) | proxy de Next sin ningún llamador | `test_fase9_camino_de_usuario.py` | **CAZADA** |
| 10 (H-16) | 15 `useState` en un componente | `test_fase10_contratos.py` | **CAZADA** |
| 10 (H-16) | renombrar un campo de un esquema Pydantic | `generate_frontend_types.py --check` | **CAZADA** |
| 12 | anular la permutación de ejes del OMF | `test_fase12_omf.py` | **CAZADA** |
| 13 | campo del store sin clasificar | `test_fase13_undo_redo.py` | **CAZADA** |
| 1 (H-37) | anular el rechazo del modo `amplitude` | `test_fase1_literal_dispatch.py` | **CAZADA** |

**La que escapó es el hallazgo de esta parte**, y no es un fallo del arnés sino una
propiedad del gate que nadie había escrito: `study_duplication.py` cuenta **huellas
distintas** compartidas entre dos ficheros, no ocurrencias. Copiar *otra vez* un bloque
que ya estaba duplicado **no mueve el número**. El criterio «< 40 ventanas» defiende
contra duplicación **nueva**, no contra que la existente se multiplique.

### 1.4.4 El patrón que la Fase 28 pidió buscar: el guard que se satisface con su propio literal

Se censaron los **29** ficheros de `tests/` que leen código fuente (`read_text`,
`ast.parse`, `glob`) y se aislaron los **11** que barren un árbol que los contiene o
que leen su propio fichero. Resultado:

- **Ninguno confirmado.** Los dos que más se acercan **ya se defienden a propósito y lo
  dicen**: `test_fase6_limpieza_verificada.py:52` excluye su propio fichero del barrido
  (`if p.name != Path(__file__).name`) y `:417-431` documenta, **con la medición**, que
  sin esa exclusión los tres contratos de `HUERFANOS_TOLERADOS` desaparecían del
  recuento. Es la patología de la Fase 6, cerrada y anotada.
- **Un agujero latente, medido y hoy inofensivo.**
  `tests/test_fase9_camino_de_usuario.py:36` incluye **`"e2e"`** en `_WEB_SCAN_DIRS`, y
  ese conjunto es el que usan `test_todo_endpoint_tiene_consumidor_o_excusa_escrita`
  (`:166`), `test_la_lista_de_rutas_toleradas_es_portante` (`:192`) y
  `test_la_superficie_f7_tiene_camino_de_usuario` (`:290`). Es decir: **una ruta cuyo
  único consumidor sea un recorrido de Playwright cuenta como “tiene camino de
  usuario”, y esos recorridos no los ejecuta nadie** (§1.4.1). Medido: de las **64**
  rutas del backend, **0** dependen hoy de eso, así que el agujero está abierto y vacío.
  Arreglo de coste cero: sacar `"e2e"` de esa tupla, o volver a ejecutar los recorridos.

---

# 2. MAPA CONCEPTUAL DEL PROYECTO (Fase 3)

## 2.1 Arquitectura real, no la del diagrama

```
┌─────────────────────────────────────────────────────────────────────────┐
│ EMPAQUE   Tauri 2 (Rust) ── 2 sidecars ── backend PyInstaller (199 MB)  │
│                                        └─ frontend Node standalone      │
├─────────────────────────────────────────────────────────────────────────┤
│ FRONTEND  Next.js 16.2 · React 19.2 · Three.js 0.183 · Zustand 5        │
│           app/ (~40 proxies) → componentes/ (vistas+paneles)            │
│           lib/render/ (13 capas GPU) · workers/ (voxelBufferBuilder)     │
│           store/useAppStore.ts (804 LOC, store único)                    │
├──────────────────────────── HTTP (proxies Next) ───────────────────────┤
│ API       FastAPI · 22 routers · 57 endpoints · schemas Pydantic        │
│           main.py: handlers "nunca-crashea" (TerraquantumError→ES)       │
├─────────────────────────────────────────────────────────────────────────┤
│ SERVICIOS 51 archivos / 26.362 LOC                                      │
│   ingesta:    sniffer→analysis→column_mapping→enrichment→package        │
│   gabinete:   corrections · earth_tide · drift · euler_spectral ·       │
│               mag_enhancement · regional_residual · potential_field_grid │
│   inversión:  geophysics_service (ORQUESTADOR, 4.708 LOC) ·             │
│               inversion_kernel/solver/postprocess · joint_inversion      │
│   datos:      block_model_service · project_store(SQLite) · export ·    │
│               isosurface · octree_mesh_builder · svdag · volumetric      │
├─────────────────────────────────────────────────────────────────────────┤
│ MOTOR     exploration/ 15 archivos / 11.023 LOC                         │
│   gravimetry.py (3.976) · magnetometry.py (3.163) · pgi_engine ·        │
│   implicit_modeling · focusing · solver_preconditioned · treemesh ·      │
│   checkerboard_test · geophysics_weights                                │
├─────────────────────────────────────────────────────────────────────────┤
│ DATOS     Parquet (block models) · Zarr (grids grandes) ·               │
│           Arrow IPC/LZ4 (transporte al visor) · SQLite (historial) ·    │
│           JSON (reportes/snapshots) · export: VTR · GSLIB · UBC msh/mod │
└─────────────────────────────────────────────────────────────────────────┘
```

## 2.2 El camino dorado, con su coste real

`CSV → sniff → mapeo → enrich → build-package → load-package (encola) → run_queue (proceso) → geophysics_service → gravimetry/magnetometry → parquet → Arrow IPC → Three.js → reporte B1/B2/B3 → export`

**[HECHO]** El flujo está completo y es coherente. **[MEDIDO]** El problema es la distribución de masa: dos funciones (`run_geophysics_inversion` 1.996 LOC + `solve_inversion_lsqr` 1.050 LOC) contienen el corazón de ese camino.

## 2.3 Distribución estructural del backend **[MEDIDO por AST]**

| Tamaño | Funciones | % | Líneas | % del código |
|---|---:|---:|---:|---:|
| 0–25 LOC | 639 | 63,1% | 6.232 | 15,1% |
| 26–50 | 156 | 15,4% | 5.708 | 13,8% |
| 51–100 | 124 | 12,3% | 8.766 | 21,2% |
| 101–200 | 72 | 7,1% | 9.752 | 23,6% |
| 201–400 | 12 | 1,2% | 3.056 | 7,4% |
| 401–1000 | 7 | 0,7% | 4.796 | 11,6% |
| **>1000** | **2** | **0,2%** | **3.046** | **7,4%** |

**Lectura correcta de esta tabla — y es importante no calumniar al proyecto:** el 63% de las funciones tiene ≤25 líneas. **El código está mayoritariamente bien factorizado.** El problema no es difuso, es **quirúrgico y localizado**: una espina dorsal de 21 funciones que acumuló toda la complejidad. Eso es una buena noticia para el plan de remediación: se sabe exactamente dónde operar.

Las peores, con sus métricas:

| LOC | args | CC | Ubicación | Función |
|---:|---:|---:|---|---|
| 1.996 | 1 | **201** | `services/geophysics_service.py:2474` | `run_geophysics_inversion` |
| 1.050 | **39** | 137 | `exploration/gravimetry.py:1728` | `solve_inversion_lsqr` |
| 927 | **41** | 164 | `api/gravity_import_api.py:1975` | `invert_gravity_csv` |
| 840 | 37 | 132 | `exploration/magnetometry.py:840` | `solve_magnetic_inversion_lsqr` |
| 777 | 6 | 185 | `services/gravity_import_service.py:888` | `_import_gravity_csv_v1_impl` |
| 731 | 1 | 94 | `services/joint_inversion.py:463` | `run_joint_inversion` |

---

# 3. MAPA CONCEPTUAL DE LOS DEEP RESEARCH (Fase 4)

## 3.1 Qué son realmente estos 13 documentos

**[OPINIÓN, pero fundada en la lectura completa del informe 13 y en la estructura de los otros 12]:** son *surveys de estado del arte de software científico nativo de gran escala*. Su sujeto implícito es un motor C++/CUDA para equipos de decenas de ingenieros, operando a exaescala, con kernels geométricos exactos y solvers distribuidos.

Esto no los invalida — los principios son de primera calidad. Pero **comparar TerraQuantum contra ellos sin ese ajuste produciría una auditoría inútil**, del tipo "le falta CGAL, PETSc, Kokkos, ECS, lock-free y MPI". El usuario pidió explícitamente distinguir qué aplica: esa es la parte más importante del trabajo.

## 3.2 El árbol de conocimiento, condensado

| # | Informe | Núcleo de lo que exige | Aplicabilidad a TQ |
|---|---|---|---|
| 01 | HPC y motores 3D | Roofline, SIMD/AVX, CUDA, DOD/SoA, arenas, job systems lock-free, task graphs, perfilado jerárquico; Pseudoflow>Lerchs-Grossmann | **Principios sí** (SoA, no romper vectorización, asincronía, perfilar antes de optimizar). **Prescripciones nativas no.** |
| 02 | Gestión de datos | Columnar, Arrow zero-copy, Parquet+predicate pushdown, SQLite como catálogo, HDF5, **OMF**, VTK, 3D Tiles, ARC, out-of-core | **Casi todo aplica y TQ ya lo cumple**, salvo OMF y versionado |
| 03 | Interacción y UX | Blender/QGIS/Leapfrog/ParaView, docking, **undo/redo**, workflows largos, colormaps perceptuales, gestión de estado | **Aplica adaptado.** El gap real de TQ está aquí |
| 04 | Motores open source | FreeCAD/Blender/OCCT/VTK/QGIS/CGAL: núcleo headless, no reescribir BRep ni render, serialización en contenedor estándar, DAG con nodos sucios, SoA, API de scripting, regresión implacable | **Auditado en §9-SEXIES.** TQ cumple 4 de 7 lecciones; falla en DAG incremental, scripting y CI de regresión. *Sus módulos 16-17 son ilegibles* |
| 05 | Ingeniería inversa del sector | Seequent/FastRBF, Maptek/out-of-core, Datamine/MSO, Deswik/CAD↔tiempo, Dassault/PLM, Kitware | **Alto valor competitivo directo** |
| 06 | CAD 3D | **TRUNCADO EN ORIGEN (57 palabras)** | No evaluable |
| 07 | Planificación minera | Fundamentos matemáticos de pit/scheduling | **No aplica hoy** (anti-scope declarado) |
| 08 | Motores gráficos 3D | Vulkan/WebGPU, render graph, forward vs deferred, gestión memoria GPU, SVO, volume rendering | **Aplica adaptado**, y TQ está sorprendentemente cerca |
| 09 | Motor de modelamiento geológico | Desurvey/mínima curvatura, implícito vs explícito, RBF/HRBF, kriging, variografía, fallas, grade shells | **Parcial**: desurvey ✅, RBF construido sin cablear |
| 10 | Kernel geométrico | BRep, Euler-Poincaré, Delaunay/CDT, QEM, **Taubin**, **marching cubes**, dual contouring, SDF, NURBS, predicados exactos | **Solo la rama de mallas implícitas**; BRep/NURBS no aplican |
| 11 | Sistema geológico-minero 3D | Clean Architecture + DDD + ECS, bounded contexts, CQRS, predicados Shewchuk, SVO+LOD, kriging, Lerchs-Grossmann, INR | **Arquitectura sí, dominio minero no** |
| 12 | IA científica | PINNs, GPs, representaciones neuronales implícitas, deep kriging, ML para block models | **Investigación, no producto** |
| 13 | Motor matemático | Álgebra lineal, **QR sobre ecuaciones normales**, SVD, sparse CSR/CSC, solvers directos vs iterativos, precondicionadores, **estabilidad y condicionamiento**, tolerancias dinámicas, propagación de error, aritmética exacta | **El más directamente aplicable de los 13** |

## 3.3 Los principios que sí atraviesan la escala

Filtrando lo dependiente de C++/exaescala, queda un núcleo que aplica **directo** a TerraQuantum:

1. **Nunca formar `AᵀA` explícitamente** (13, Mód. 7): el condicionamiento se eleva al cuadrado y se pierde la mitad de los dígitos significativos.
2. **El condicionamiento es una propiedad del problema, no del algoritmo** (13, Mód. 12): distinguir error del problema (→ regularizar) de error del algoritmo (→ es un bug de arquitectura).
3. **Tolerancias relativas escaladas al problema, nunca constantes cósmicas** (13, Mód. 18).
4. **Formatos ASCII solo en la frontera; columnar dentro** (02).
5. **Inmutabilidad / append-only para datos científicos** (02).
6. **Los flujos largos nunca bloquean; progreso y cancelación son requisitos, no lujos** (01, 03).
7. **Colormaps perceptualmente uniformes; el arcoíris miente** (03, Mód. 13).
8. **Separar el marco cronológico-topológico del motor de interpolación** (09).
9. **Comprar antes que construir, salvo en el núcleo diferenciador** (11, §4.1).
10. **Fuzzing y property-based testing en CI** (11, §8.2).

---

# 4. MATRIZ DE COBERTURA

Escala: **0%** no existe · **10%** vestigio · **25%** parcial no usable · **50%** funcional con huecos · **75%** sólido con deuda · **90%** industrial · **100%** referencia.

## 4.1 Motor matemático (informe 13)

| Tema | Existe | Nivel | Calidad | Escalab. | Prior. | Archivos | Comentario |
|---|---|---:|---|---|---|---|---|
| Solvers iterativos (LSQR/LSMR) | ✅ | **90%** | Alta | Alta | — | `gravimetry.py:2546`, `solver_preconditioned.py:55` | LSMR con umbral 50k, justificación Fong & Saunders citada. Correcto |
| Regularización Tikhonov + IRLS compacto | ✅ | **90%** | Alta | Alta | — | `gravimetry.py:2390-2618` | Minimum-support Last&Kubik/Portniaguine bien implementado, con ε enfriado y clip [0.05,20] |
| **Depth weighting Li & Oldenburg** | ⚠️ | **0%** | **Nula** | — | **P0** | `gravimetry.py:2196-2248` | **[MEDIDO] Algebraicamente inerte.** Ver H-1 |
| Bounds petrofísicos / KKT | ✅ | **75%** | Media-alta | Media | P2 | `gravimetry.py:2504` | TRF real solo si n≤8.000; por encima es LSQR+clip (+FISTA). El clip no resuelve el problema acotado |
| Selección de λ (Morozov/L-curve) | ✅ | **75%** | Alta | Media | P2 | `gravimetry.py:1289,1547` | Medido frágil en profundo por aplanamiento de χ²(λ) — documentado honestamente |
| **Evitar ecuaciones normales** | ⚠️ | **50%** | — | — | **P1** | `gravimetry.py:2513-2529` | La ruta existe, viola el informe 13 §7, y **está rota** (H-2). Default OFF |
| Estabilidad / condicionamiento | ✅ | **75%** | Alta | — | P2 | `gravimetry.py:2459-2478` | cond(A) estimado O(nnz) sin SVD + auto_kappa. Buena ingeniería |
| Propagación de error / UQ | ⚠️ | **50%** | Media | Media | P2 | `gravimetry.py:2779` | Hutchinson implementado, **desactivado por defecto** con razón explícita |
| Tolerancias dinámicas | ⚠️ | **50%** | Media | — | P3 | disperso | Muchos umbrales absolutos (1e-6, 1e-12, 8000, 1e12) con justificación empírica documentada, pero fijos |
| SVD / truncated SVD | ❌ | 0% | — | — | P4 | — | No necesario a esta escala |
| Aritmética exacta / predicados | ❌ | 0% | — | — | **N/A** | — | **No aplica**: no hay booleanas CAD |
| Cuaterniones | ➖ | — | — | — | N/A | Three.js | Delegado al motor 3D. Correcto |

## 4.2 Gestión de datos (informe 02)

| Tema | Existe | Nivel | Comentario |
|---|---|---:|---|
| Columnar / Parquet | ✅ | **90%** | Polars + Parquet en block models. Exactamente lo prescrito |
| Arrow zero-copy | ✅ | **75%** | `block_model_service.py:1206-1216` IPC con LZ4 al visor. Muy bien |
| Zarr para grids grandes | ✅ | **75%** | Ruta >500k vóxeles |
| SQLite como catálogo | ✅ | **90%** | `project_store.py`, WAL, reconciliación de huérfanas al arrancar. Patrón canónico del informe |
| ASCII solo en frontera | ✅ | **90%** | CSV entra, parquet dentro. Cumple el principio |
| Predicate pushdown | ⚠️ | 25% | Se lee parquet pero no explota estadísticas de footer |
| **OMF (Open Mining Format)** | ❌ | **0%** | **Gap real.** Informes 02 §9 y 11 §4.6 lo tratan como el antídoto al lock-in. Export hay VTR/GSLIB/UBC |
| Versionado de datos | ❌ | 10% | Historial de corridas ≠ versionado espacial por deltas (Seequent Central, informe 05 §1.4) |
| Streaming / 3D Tiles | ⚠️ | 25% | LOD por umbral, no jerarquía espacial servida |
| Caché jerárquico (ARC) | ❌ | 0% | No aplica a esta escala |

## 4.3 Render 3D (informe 08)

| Tema | Existe | Nivel | Archivos | Comentario |
|---|---|---:|---|---|
| Instancing | ✅ | **90%** | `Scene3D.tsx:581` | `InstancedMesh` con bounding sphere explícita |
| Isosuperficies | ✅ | **90%** | `isosurface_service.py:338` + `IsosurfaceMeshLayer` | **Marching cubes en backend** (skimage) + Taubin. Exactamente informe 10 §6.3/§8.1 |
| Clipping / secciones | ✅ | **90%** | `SectionPaintLayer`, `SliceControls` | Cara del corte pintada |
| Volume raymarching | ✅ | **75%** | `VolumeRaymarchLayer.tsx` | Cableado y opt-in |
| Ambient occlusion | ✅ | 75% | `SubsurfaceAOEffect.tsx` | Cableado |
| LOD | ⚠️ | **50%** | `Scene3D.tsx:547` | Umbral fijo 50k + worker. No jerárquico (informe 08 pide SVO) |
| Culling | ⚠️ | 50% | `Scene3D.tsx:1081` | `frustumCulled={false}` con gestión manual |
| **Render graph** | ❌ | **10%** | `reactiveUpdateGraph.ts` | **[MEDIDO] Construido, 0 consumidores** (H-6) |
| **WebGPU compute cull** | ❌ | **10%** | `webgpuCull.ts` | **[MEDIDO] Cadena muerta** (H-6) |
| SVO / ESVO | ⚠️ | 25% | `svdag_service.py` | Backend construido, sin cablear |
| Gestión memoria GPU | ✅ | 75% | `Scene3D.tsx:602-605` | `dispose()` explícito de geometría y materiales |
| Colormaps científicos | ✅ | **90%** | `terraQuantumGeology.ts` | Viridis, decisión medida contra arcoíris |

## 4.4 Geología (informes 09, 10, 11)

| Tema | Existe | Nivel | Comentario |
|---|---|---:|---|
| Desurvey mínima curvatura | ✅ | **90%** | `borehole_desurvey_service.py`, validado contra cálculo manual de 3 tramos |
| QA/QC de sondajes | ✅ | **90%** | 7 defectos detectados con fila y severidad |
| Compositación | ✅ | 75% | Implementada |
| **RBF / HRBF implícito** | ⚠️ | **25%** | `implicit_modeling.py` (533 LOC) existe y tiene tests, **sin cablear a producción**. Informes 09 §5-6, 10 §8.4 y 11 §6.1-6.2 lo tratan como *el* núcleo geológico |
| PGI / GMM petrofísico | ⚠️ | **50%** | `pgi_engine.py` (387 LOC) implementado, uso condicional |
| Kriging / variografía | ❌ | **0%** | Ausente. Decisión correcta y ya declarada anti-scope |
| Fallas como red topológica | ❌ | 0% | Ausente |
| Grade shells | ❌ | 0% | Ausente (requiere ensayos, fuera de scope) |
| Marching cubes / SDF | ✅ | 90% | Ver §4.3 |
| Dual contouring | ❌ | 0% | No necesario sin aristas vivas |
| BRep / NURBS / booleanas exactas | ❌ | 0% | **No aplica**: TQ no es CAD |

## 4.5 Minería (informes 07, 11)

| Tema | Existe | Nivel | Comentario |
|---|---|---:|---|
| Block model como estructura | ✅ | 75% | `block_model_service.py`, `block_model_store.py` — pero es un modelo de *densidad invertida*, no económico |
| Lerchs-Grossmann / Pseudoflow | ❌ | **0%** | **[MEDIDO]** Cero ocurrencias en el repo |
| Scheduling / CPM | ❌ | 0% | Ausente |
| Cutoff grade / NPV | ❌ | 0% | Ausente — y **prohibido explícitamente** en salidas por compliance JORC |
| Stopes / MSO | ❌ | 0% | Ausente |
| Diseño de tronadura | ❌ | 0% | Ausente |
| Geometalurgia | ❌ | 0% | Ausente |

**[OPINIÓN] Esta fila de ceros es una decisión de producto correcta, no una deuda.** El informe 05 §3.4 y la propia investigación de mercado del proyecto coinciden: competir con Datamine/Deswik en planificación sería suicida para un equipo de una persona. Lo que **sí** debe hacerse es blindar el anti-scope: hoy vive en `docs/02_PRODUCTO.md` §6, pero un inversor lo leería como "roadmap futuro". Debe decir *nunca*.

## 4.6 HPC (informe 01)

| Tema | Existe | Nivel | Comentario |
|---|---|---:|---|
| Vectorización SIMD | ✅ | **90%** | Vía numpy/scipy/BLAS. **El informe se cumple sin escribir intrínsecos** |
| Estructuras columnares (SoA) | ✅ | 90% | Arrays numpy + parquet. DOD de facto |
| Paralelismo de tareas | ⚠️ | **50%** | `ThreadPoolExecutor` en el forward (`gravimetry.py:889`) + `run_queue_service` con proceso spawn. Correcto para CPU-bound con GIL |
| Dask / out-of-core | ⚠️ | 25% | `compute_jacobian_dask` con streaming a Zarr, scheduler síncrono |
| GPU compute (CUDA/OpenCL) | ❌ | **0%** | **[MEDIDO]** Sin numba, cupy ni kernels |
| Job system lock-free | ❌ | 0% | **No aplica.** El propio informe admite "extrema complejidad de validación" |
| ECS formal | ❌ | 0% | **No aplica** a 1 persona |
| Perfilado sistemático | ⚠️ | 50% | Hay mediciones puntuales excelentes (7,16 ms/vóxel joint calibrado) pero no perfilado jerárquico |

**[OPINIÓN]** Los ceros de esta tabla son **correctos**. Recomendar CUDA o lock-free aquí sería exactamente el tipo de consejo que destruye proyectos de una persona. El informe 01 mismo dice "optimizar solo tras perfilar", y TQ no tiene evidencia de estar limitado por cómputo en el rango que vende (30k vóxeles < 3 min).

## 4.7 UX (informe 03)

| Tema | Existe | Nivel | Comentario |
|---|---|---:|---|
| Flujos largos con progreso | ✅ | **90%** | Cola + polling 1,5 s + etapas + cancelar. Requisito central del informe, cumplido |
| Errores accionables | ✅ | **90%** | Catálogo de 60 errores en español + `ErrorModal` |
| Colormaps perceptuales | ✅ | 90% | Viridis |
| Historial de proyectos | ✅ | 75% | SQLite persistente |
| **Undo / Redo** | ❌ | **0%** | **[MEDIDO]** Ausente. Informe 03 Mód. 8 lo trata como arquitectura fundacional. **✅ CERRADO en la Fase 13 (08-19)**: Command Pattern por deltas sobre 16 claves del visor + `contexto`/`parametros` de preparación, con techo de 50, barrera en cambio de archivo y clasificación de los 100 campos del store obligada por el compilador |
| Docking de paneles | ❌ | 0% | Layout fijo. **NO se hará**: §9H.2 lo declara sobreingeniería para un flujo lineal de 3 zonas |
| Atajos / paleta de comandos | ⚠️ | 25% | Solo `onKeyDown` puntual en 2 componentes. **✅ Parcial en la Fase 13**: Ctrl+Z/Ctrl+Y con aislamiento de foco y una sola declaración de teclas — y ahí se midió que el listener de `Scene3D` **secuestraba** las flechas de los 8 sliders del visor. **Sigue sin paleta de comandos** |
| Automatización / scripting | ❌ | 0% | Sin API de scripting para el usuario experto. **✅ CERRADO en la Fase 11 (08-17)** |
| Accesibilidad | ⚠️ | 25% | *cobertura parcial: no auditado en profundidad* |

**[OPINIÓN]** Aquí está el gap más grande y menos reconocido del proyecto. La UX es el eje donde Leapfrog gana, y donde el plan maestro no tiene una fase asignada. Undo/redo en particular: **añadirlo tarde es carísimo** porque obliga a rediseñar todas las mutaciones de estado.

## 4.8 IA (informe 12)

| Tema | Existe | Nivel | Comentario |
|---|---|---:|---|
| Copiloto anclado a datos | ✅ | **75%** | `gemini_agent.py` + `chat_api.py`: grounding B1/B2/B3, guard de anclaje numérico, palabras prohibidas JORC. **Diseño maduro** |
| BYO-key / privacidad | ✅ | 90% | Coherente con local-first |
| Context caching | ✅ | 75% | Opt-in |
| PINNs | ❌ | 0% | **No aplica**: investigación |
| Neural implicit / deep kriging | ❌ | 0% | **No aplica** |
| ML para clasificación de mineral | ❌ | 0% | **No aplica** sin ensayos |

**[OPINIÓN]** El informe 12 es el que **menos** debe seguirse. TQ tomó la decisión correcta y la documentó ("a Gemini no se le entrena"). Un PINN aquí sería una respuesta sofisticada a una pregunta que nadie hizo.

---

# 5. AUDITORÍA DE ARQUITECTURA

## 5.1 Lo que está bien diseñado

**Separación backend/frontend con frontera física real.** No es solo una convención de carpetas: hay un revisor automático (`.claude/agents/frontend-physics-boundary-reviewer`) que audita que el frontend no calcule física. **[MEDIDO]** Busqué constantes gravitacionales, fórmulas de prisma y kernels en TS: el único hallazgo es `engine-physics.ts`, un generador procedural de demo explícitamente marcado "No importar en flujos de inversión" y **sin importadores** (H-6). **La frontera se respeta.** Esto es raro y valioso.

**La cadena de ingesta.** `sniffer → analysis → column_mapping → enrichment → package` tiene responsabilidades limpias, cada eslabón es testeable en aislamiento, y el contrato `needs_context` (preguntar en vez de inventar) es una decisión de diseño de primer nivel. **[OPINIÓN] Es la mejor pieza de arquitectura del proyecto** y, no por casualidad, la que más valor de producto genera.

**Local-first como restricción arquitectónica, no como feature.** SQLite en vez de Postgres, Ed25519 offline en vez de servidor de licencias, IGRF embebido, cero Redis. El informe 02 §5.1 valida explícitamente este patrón. La eliminación de Celery en F3 —con grep de cero llamadores como evidencia— es exactamente cómo debe tomarse una decisión así.

**El reporte honesto B1/B2/B3.** Arquitectónicamente es un *pipeline de veredictos reconciliados* con `worst-of-chain` (`geophysics_service.py:809`). Que el veredicto global no pueda ser mejor que su eslabón más débil es una decisión de diseño que protege contra la corrupción silenciosa. **[OPINIÓN] Esto es el producto.**

## 5.2 Lo que está mal diseñado

**Arquitectura de acreción.** El patrón es visible y sistemático: cada fase (F0.2, F0.8, F0.9, R-02, R-05, F8, F9C-1, F14, F16, F18, F24B, F2.1, F2.3) añadió **parámetros y ramas guardadas dentro de las mismas funciones** en lugar de piezas componibles. El resultado son firmas de 39–41 parámetros y CC de 137–201.

Esto no es pereza: es la consecuencia natural de "no hacer refactors globales" (regla del repo) sostenida durante 25 fases. La regla protegió la estabilidad del motor validado —lo cual fue **correcto**— pero su coste se acumuló íntegro en el camino crítico.

**Acoplamiento del núcleo numérico a configuración global.** `gravimetry.py:2480,2513,2563` importa `core.config` **dentro del bucle IRLS**. El comportamiento del solver depende de variables de entorno que no aparecen en su firma. **[INFERENCIA]** Consecuencias: la reproducibilidad de una corrida no está determinada por sus parámetros; dos ejecuciones con idéntico input pueden diferir según el entorno; y el path de H-2 sobrevivió invisible precisamente porque nadie lo ejerce.

**Inversión de dependencias ausente en el eje que importa.** `geophysics_service` importa `exploration.gravimetry` concretamente. No hay interfaz `ForwardOperator`/`Solver` que permita sustituir el motor. **[OPINIÓN]** Para un producto de un solo motor esto es aceptable hoy; se vuelve bloqueante cuando entre la segunda física (IP/EM/MT del plan F11).

**El handler HTTP que hace todo.** `invert_gravity_csv` (927 LOC, 41 args, CC=164) mezcla parsing HTTP, validación, orquestación física y serialización. Viola la separación de capas de cualquiera de los informes.

## 5.3 Clean Architecture / DDD / Hexagonal (informe 11 §2)

**[OPINIÓN, y aquí discrepo del informe]:** el informe 11 prescribe Clean Architecture + DDD + ECS con cuatro *bounded contexts*. Para TerraQuantum eso sería **sobreingeniería severa**. Un equipo de una persona con un dominio único no necesita contextos delimitados; necesita módulos con fronteras claras, que es un subconjunto mucho más barato.

Lo que **sí** debe tomarse del informe 11: la **separación entre el marco topológico-cronológico y el motor de interpolación** (informe 09 §4.1), que traducida a TQ significa separar *orquestación de corrida* de *física de inversión*. Hoy están fundidas en `run_geophysics_inversion`.

---

# 6. AUDITORÍA MATEMÁTICA

## 6.1 Calidad de la formulación

**[HECHO] La matemática está por encima de lo que el tamaño del proyecto haría esperar.** Referencias correctas y citadas en el código: Li & Oldenburg 1996/1998/1999 (depth weighting, modelo de referencia), Last & Kubik 1983 y Portniaguine & Zhdanov 1999 (minimum support), Fong & Saunders 2011 (LSMR), Nagy (prisma), Bhattacharyya/Sharma (TMI), Gallardo-Meju (cross-gradient), Longman 1959 (marea).

Aciertos concretos:

- **Orden explícito de pesos** documentado (`Wd → Wz → Ws`, línea 2212) — muestra conciencia del problema.
- **Transformación consistente de bounds** a través de toda la cadena de escalado (2205-2230). Es un error clásico y aquí está bien hecho.
- **Ancla dura por eliminación de variables** (2376-2385): en vez de penalización fuerte con κ grande —que destruiría el condicionamiento— elimina la columna y reinyecta. **[OPINIÓN] Es la solución correcta y elegante.**
- **σ adaptativo invariante de escala** con MAD para outliers (2140-2155), en lugar de un `noise_floor` absoluto que sería absurdo en unidades SI.
- **Poda del dominio observable R-05** (2074-2117): eliminar columnas de sensibilidad nula evita el plateau de χ² por mínima norma. Diagnóstico fino.
- **χ² y misfit reportan NaN** ante datos degenerados en vez de fingir ajuste perfecto (2686-2690). Coherente con la filosofía anti-corrupción-silenciosa.

## 6.2 H-1 en detalle — el hallazgo crítico

### El código

```python
# gravimetry.py:2196-2248 (abreviado)
wz_inv_diag = (true_depth + z0) ** (0.5 * float(depth_beta))
wz_inv_diag = wz_inv_diag / np.mean(wz_inv_diag)
Wz_inv   = sp.diags(wz_inv_diag)
G_scaled = G_w @ Wz_inv                                    # (1)
_col_norms_wz = np.sqrt(G_scaled.power(2).sum(axis=0)).A1  # (2)
Ws       = sp.diags(1.0 / _col_norms_wz)
G_scaled = G_scaled @ Ws                                   # (3)
Wz_inv   = Wz_inv @ Ws        # m = Wz_inv_combined @ m_tilde
```

### La demostración

Sea `g_j` la columna *j* de `G_w` y `w_j = wz_inv_diag[j]`.

- Por (1): columna *j* de `G_scaled` = `w_j · g_j`
- Por (2): `col_norms[j] = ‖w_j · g_j‖ = w_j · ‖g_j‖`  (porque `w_j > 0`)
- Por (3): columna *j* final = `w_j · g_j / (w_j · ‖g_j‖)` = **`g_j / ‖g_j‖`**

`w_j` **se cancela idénticamente**. Y `Wz_inv_combined[j] = w_j / (w_j·‖g_j‖) = 1/‖g_j‖`, también independiente de `w_j`. Como los bounds se construyen con `(d−base)/w_j · col_norms[j] = (d−base)·‖g_j‖`, **tampoco dependen de β**.

### La verificación **[MEDIDO]**

Reproduje la cadena exacta con un kernel gravimétrico sintético y comparé todas las cantidades aguas abajo contra `depth_beta=2.0`:

| β | ΔG_scaled | ΔL_scaled | Δbounds | ΔWz_comb |
|---|---|---|---|---|
| 0,0 | 1,7e-16 | 5,8e-11 | 2,6e-18 | 1,5e-11 |
| 0,5 | 1,7e-16 | 4,4e-11 | 2,6e-18 | 1,5e-11 |
| 1,0 | 1,7e-16 | 5,8e-11 | 8,7e-19 | 2,9e-11 |
| 3,0 | 2,2e-16 | 5,8e-11 | 2,6e-18 | 1,5e-11 |
| 6,0 | 1,7e-16 | 5,8e-11 | 1,7e-18 | 2,2e-11 |

Todo a nivel de ruido de punto flotante. Identidades predichas confirmadas: `Wz_comb == 1/‖col(G_w)‖` (error 1,5e-11) y `G_scaled == G_w/‖col‖` (error 1,7e-16).

*(Script reproducible: `scratchpad/audit/verify_wz_cancel.py`)*

### Qué significa realmente

1. **El parámetro `depth_beta` no hace nada.** Los ~60 líneas de comentario que documentan "H-A0 Bug 1: W_z formal Li & Oldenburg — elimina la doble compensación de profundidad" describen un efecto que no ocurre. **El código miente sobre sí mismo**, sin mala fe: alguien implementó el cambio de variable correcto y luego añadió la normalización de columnas, sin notar que la segunda anula la primera.

2. **El funcional de regularización real no es el documentado.** El término de *smallness* penaliza `‖m̃‖²`, que en espacio físico equivale a **`Σⱼ (mⱼ · ‖colⱼ(W_d·G)‖)²`**. Es decir, TQ **sí** tiene un peso de modelo dependiente de la profundidad —porque la norma de columna decae con la profundidad— pero es **ponderación por sensibilidad con exponente 1**, no el depth weighting `(z+z₀)^(−β/2)` de Li & Oldenburg, y **no es ajustable por ningún parámetro expuesto.**

3. **Explica de un golpe semanas de experimentos.** El proyecto midió empíricamente que `depth_beta` era inerte (F9), que el "W_z-fix" era inerte y lo revirtió (Punto 4), y que la dirección del sesgo de profundidad cambia según el régimen (hundimiento en LdM, apilamiento somero en sintéticos). Las tres observaciones son consecuencias de la misma causa: **el peso de modelo efectivo es `‖colⱼ‖`, que en gravimetría decae aproximadamente como 1/z², un peso mucho más agresivo y de forma distinta al estándar industrial.** Un peso demasiado fuerte empuja masa al fondo; combinado con λ pequeño que sobreajusta, apila somero. Ambos regímenes observados son coherentes con esta explicación.

4. **[INFERENCIA, la parte que hay que MEDIR, no creer]:** si se separa la normalización de columnas (como *precondicionador* dentro del solver, que no cambia la solución del problema regularizado) del peso de modelo (como `W_m` explícito en el funcional, que sí la cambia), `depth_beta` recuperaría su efecto y la profundidad pasaría a ser ajustable. **Podría mejorar sustancialmente la recuperación de profundidad — o podría confirmar que la ley del null-space domina de todos modos.** Ambos resultados son valiosos: el primero es un producto nuevo; el segundo cierra definitivamente la pregunta y permite vender el límite con autoridad.

Este es exactamente el tipo de experimento que el proyecto sabe hacer (harness de error budget con verdad analítica ya existe). **Es la recomendación #1 de esta auditoría.**

> **✅ HECHO — Fase 4, 2026-08-14. Salió el segundo resultado.** 3.450 inversiones con Morozov re-eligiendo λ en cada brazo: **ningún β fijo mejora la profundidad** en los cuatro regímenes y las tres configuraciones. La perilla revive (β=0 vs β=2 mueve el modelo un 49,8 % del pico) pero no tiene un valor universal — β=1,5 rescata 900 m (88 m vs 538 m) y arruina 300 m (175 m vs 12 m). **Y dos correcciones a lo que se acaba de leer arriba:** (1) el peso efectivo **no** decae «como 1/z² y de forma distinta al estándar»: ajusta a `(z+z₀)^(−β/2)` con **β=2,63** y 5,3 % de desviación — misma familia que Li & Oldenburg, y el brazo separado que mejor compite es justo β=3; (2) el peso está muerto en `solve_inversion_lsqr` pero **vivo en `solve_inversion_treemesh`** (8.125× más), que producción elige sola por tamaño de survey. Registro completo en §FASE 4.

## 6.3 H-2 — camino de ejecución imposible

**[MEDIDO]** `gravimetry.py:2519` invoca `solve_sparse_normal_equations(...)`. Verificado por AST del módulo, por búsqueda en todo el repositorio y por introspección tras importar: **el símbolo no está definido, no está importado, no es atributo del módulo ni builtin.** Con `USE_SPARSE_DIRECT=true` (`core/config.py:112`, default `false`) la inversión aborta con `NameError` **después** de construir el kernel — el punto más caro del pipeline.

Agravante conceptual: aunque estuviera implementado, el propio comentario lo describe como "SuperLU sobre ecuaciones normales", que es precisamente lo que el informe 13 §7 califica de "numéricamente imperdonable" (cond² ⇒ pérdida de la mitad de los dígitos). El proyecto **ya aprendió la lección** —el comentario de la línea 2534 dice literalmente "NO forma AᵀA explícitamente (lección Sprint 5A)"— pero el cadáver del experimento quedó cableado y roto.

**Recomendación: borrar el bloque y la variable de configuración.** No repararlo.

**[INFERENCIA] Lección de proceso más importante que el bug:** ninguna prueba ejerce las variables de entorno documentadas. Un test que recorra los flags de `core/config.py` y verifique que cada camino al menos importa y arranca habría cazado esto el día que se escribió.

## 6.4 Riesgos numéricos restantes

| Riesgo | Ubicación | Severidad | Comentario |
|---|---|---|---|
| `LSQR + clip` no resuelve el problema acotado | `2551` | Media | Reconocido en el código ("misfit degradado ~35%"), mitigado con FISTA. Honesto |
| Umbral TRF n≤8.000 fijo | `2486` | Media | Justificado con benchmark de 2026-06-01. Envejecerá con el hardware |
| `compact_max_irls=8` sin criterio de convergencia duro | `2396` | Baja | Hay `compact_tol`, pero el corte por iteraciones es el que domina |
| `_focus_w` con clip `[0.05, 20]` | `2604` | Baja | Estabilizador empírico, no justificado en literatura citada |
| Estimación de cond(A) por ratio de normas de columna | `2465` | Baja | Es una **cota inferior**, no cond(A). El log dice "cond(A)~" — correcto, pero puede infraestimar mucho |

---

# 7. AUDITORÍAS RESTANTES (condensadas)

## 7.1 Geometría

**[HECHO]** `isosurface_service.py:338` usa `skimage.measure.marching_cubes` + suavizado Taubin (`:269`) parametrizable desde la API (`block_model_api.py:183`, `taubin_iterations` 0–100). Esto implementa exactamente lo que el informe 10 §6.3 prescribe (Taubin sobre Laplaciano para no encoger volumen) y §8.1 (marching cubes). **Decisión excelente: comprar el algoritmo maduro (scikit-image) en vez de implementarlo.** Coincide con el principio "comprar antes que construir salvo en el núcleo diferenciador" (informe 11 §4.1).

Lo ausente (BRep, NURBS, booleanas exactas, predicados de Shewchuk, Delaunay/CDT, dual contouring) **no aplica**: TerraQuantum no hace CAD ni modelado explícito. Recomendar CGAL aquí sería un error de auditoría.

**Gap real:** `implicit_modeling.py` (RBF/HRBF, 533 LOC, con tests) está construido y **sin cablear**. Los informes 09, 10 y 11 coinciden en que ése es el núcleo del modelamiento geológico moderno. Es la pieza con mayor ratio valor/esfuerzo del inventario.

## 7.2 Render

Ver matriz §4.3. **[OPINIÓN]** El frontend está **mejor** de lo que la documentación del proyecto sugiere: 13 capas de render, la mayoría cableadas, con isosuperficies, cortes pintados, raymarch volumétrico, AO subsuperficial, overlay de DOI y capa de sondajes. Contra el informe 08, lo que falta es *jerarquía*: LOD por umbral fijo en vez de octree, sin render graph (el archivo existe, muerto), sin culling GPU (cadena muerta).

**[INFERENCIA]** Para el rango de 30k–100k vóxeles que el producto declara soportar, esto es **suficiente**, y construir SVO+render graph sería sobreingeniería. Se vuelve necesario solo si el producto sube un orden de magnitud.

## 7.3 Datos

Ver matriz §4.2. **[OPINIÓN] El área mejor alineada con su informe.** Parquet + Arrow IPC/LZ4 + Zarr + SQLite es, casi literalmente, el blueprint del informe 02 para un motor local. El único gap con valor comercial es **OMF**: es el formato con el que un consultor entrega a una minera que usa Vulcan o Leapfrog. Sin OMF, TQ es una isla.

## 7.4 Calidad de software

**Código muerto [MEDIDO]:**
- Frontend: `reactiveUpdateGraph.ts` (8,8 KB, 0 consumidores), cadena `InstancedSegmentsLayer.tsx` + `segmentLOD.ts` + `webgpuCull.ts` (~23 KB, sin importadores externos), `engine-physics.ts` (2,5 KB, física de demo en TS sin importadores).
- Backend: el bloque `USE_SPARSE_DIRECT` (H-2).
- El propio `docs/03_MAPA_CODIGO.md` admite: *"Pendiente 2ª pasada: … áreas frontend (componentes/lib) archivo por archivo"*. **La poda de F1 nunca llegó al frontend.** Confirmado.

**Degradación silenciosa [MEDIDO]:** 63 bloques `except → pass/continue` en backend. **Cero `except:` desnudos** (excelente). Los `except Exception: pass` en `run_queue_service.py` (3 casos) y `geophysics_service.py` (2) merecen revisión individual: en un servicio de cola, tragar excepciones puede dejar corridas en estado inconsistente.

**Deuda declarada:** solo 18 marcadores TODO/FIXME/HACK en 110k LOC. **[OPINIÓN]** Inusualmente bajo. La deuda de este proyecto no está en comentarios: está en `docs/01_PLAN_MAESTRO.md`, explícita y con fase asignada. Eso es **mejor** que TODOs dispersos.

**Configuración duplicada / flags olvidados:** `USE_SPARSE_DIRECT` (roto), `USE_BOUNDED_SOLVER`, `USE_LSMR_LARGE`, `USE_PROJECTED_SOLVER`, `LSMR_THRESHOLD_N_ACTIVE`, `TQ_AUTH_ENABLED` (documentado como "rompería la UI si se activa"). **Ningún test los ejercita.**

## 7.5 Testing y CI

**Lo bueno:** 204 archivos de test, ~41k LOC. Fuzzer propio sin dependencias (106/106 sin 5xx pelados), soak sin fuga medida, matriz E2E 20/20, presupuestos de rendimiento, Playwright 6/6, y gates que **miden de verdad** contra verdad conocida en vez de hacer smoke. La prueba de degradación de F9 (romper el kernel a propósito y verificar que Raglan pasa de 212 m a 1.570 m y **falla**) es una técnica de validación que la mayoría del software industrial no practica. **[OPINIÓN] Esto es de nivel profesional.**

**H-4 [MEDIDO]:** `tests/conftest.py:14-18` salta la suite `validation` salvo `TQ_RUN_VALIDATION=1`. La CI (`.github/workflows/ci.yml:34`) ejecuta `pytest tests/ -m "not slow"` y **no define esa variable**. Por tanto **la regresión física de F9 nunca corre automáticamente.** La fase F9 se declaró cerrada con el criterio "congela la física para siempre" — pero el congelador solo funciona a mano.

**H-5 [MEDIDO]:** `ci.yml:28` compila `api services exploration schemas Camiones core middleware workers`. `Camiones` y `workers` **no existen** (`workers/` se borró en F3). `compileall` imprime "Can't list 'workers'" y **devuelve exit 0** — la CI pasa sin notarlo. Verificado ejecutándolo.

**Gap:** el informe 11 §8.2 pide property-based testing en CI. Existe (generativo, 10.000 casos) pero **fuera de la CI** por tiempo.

## 7.6 Seguridad y empaque

**H-7 [HECHO]:** `credenciales_gee.json.REVOKED_2026-06-03` está trackeado por git y contiene un bloque `-----BEGIN PRIVATE KEY-----` real con su `private_key_id`. Está revocada y renombrada, lo cual demuestra que se gestionó el incidente. Pero **sigue en el árbol de trabajo y en toda la historia de git**. Si el repositorio se hace público, se comparte con un inversor o se sube a un servicio de análisis, ese blob viaja. **Recomendación: borrar del árbol; purgar de la historia solo si el repo va a salir de la máquina.**

Lo demás está bien: `.gitignore` cubre `.env`, `.env.*`, `*.key`, `*.secret`, `secrets/`; solo hay `.env.example` committeados; el licenciamiento Ed25519 es offline y el diagnóstico exportable se probó con un secreto sembrado.

**Empaque:** *cobertura parcial — no auditado en profundidad por la caída de los agentes.* La arquitectura de 2 sidecars (backend PyInstaller + frontend Node standalone conservando los ~40 proxies) es **[OPINIÓN] la decisión correcta**: reescribir los proxies para `output:'export'` habría duplicado lógica de transformación, que es exactamente el error que las reglas del repo prohíben.

## 7.7 IA

Ver matriz §4.8. El diseño de grounding —anclar cada afirmación al `report_payload` real de la corrida, con guard de compliance por número+unidad y palabras prohibidas JORC— es **[OPINIÓN] la arquitectura correcta para IA en software que alguien firma**. El informe 12 propone PINNs y kriging neuronal; ninguno tiene sentido aquí y el proyecto acertó al rechazarlos explícitamente.

---

# 8. BENCHMARK INDUSTRIAL

Comparación **arquitectónica**, no de marketing. Basada en el informe 05 (ingeniería inversa del sector) contrastado con lo que medí en el código.

| Eje | Leapfrog/Seequent | Vulcan/Maptek | TerraQuantum | Veredicto |
|---|---|---|---|---|
| Núcleo matemático | FastRBF C++, kd-trees/octrees | Híbrido C++/script, out-of-core | numpy/scipy, LSQR/LSMR/IRLS | **Por debajo en escala, comparable en corrección**. TQ resuelve un problema distinto (inversión, no interpolación) |
| Modelamiento implícito | **Su producto entero** | Sí | RBF/HRBF construido, **sin cablear** | **Muy por debajo.** Gap conocido |
| Inversión geofísica | No es su fuerte (Seequent la delega) | Limitado | **Su producto entero, validado ×4** | **Ventaja conceptual real de TQ** |
| Datos masivos | Central, versionado por deltas | Isis, out-of-core, LOD | Parquet/Zarr/Arrow, un orden de magnitud menos | Por debajo, **adecuado a su escala** |
| Honestidad de la incertidumbre | Limitada | Limitada | **B1/B2/B3, DOI, veredicto worst-of** | **Ventaja diferencial. Nadie más lo hace así** |
| Interoperabilidad | OMF nativo | OMF | VTR/GSLIB/UBC, **sin OMF** | **Por debajo. Gap accionable** |
| UX / workflows | Referencia del sector | Denso pero potente | Guiado, sin undo/docking | **Por debajo** |
| Precio / accesibilidad | US$156/día | Licencia alta | Local-first, español | **Ventaja de mercado** |

**[OPINIÓN] La conclusión estratégica:** TerraQuantum no compite con Leapfrog. Compite con **el Excel + Oasis montaj + criterio del consultor**. Y contra ese competidor real, gana en automatización del gabinete y en honestidad cuantificada. El error estratégico posible sería intentar cerrar los gaps de la columna "por debajo" (modelamiento implícito, datos masivos, UX de Leapfrog) en vez de profundizar la columna "ventaja".

---

# 9. LO QUE HAY QUE MANTENER EXACTAMENTE IGUAL

Un auditor que solo señala defectos es un auditor incompleto. Esto **no se toca**:

1. **La disciplina de medir antes de prometer.** Es el activo más valioso del proyecto y no está en el código.
2. **El motor validado contra 4 benchmarks externos.** DO-27 53,7 m, Raglan 212 m, San Nicolás 125 m, LdM χ²=0,92. **No refactorizar sin la suite de regresión corriendo.**
3. **El contrato `needs_context`** (preguntar en lugar de inventar). Es la razón de que la ingesta no corrompa en silencio.
4. **El veredicto `worst-of-chain`.** Un diagnóstico global que no puede superar a su eslabón más débil.
5. **La regla de no tocar backend y frontend en la misma iteración.** Parece burocracia; es lo que ha mantenido la frontera física intacta durante 25 fases.
6. **El anclaje duro por eliminación de variables.** Matemáticamente correcto y elegante.
7. **La eliminación de Celery con evidencia de cero llamadores.** El modelo de cómo se borra algo.
8. **La documentación de límites físicos como leyes.** `docs/05` es un documento que muchas empresas no se atreverían a escribir.
9. **El Morozov de producción: escanear con el solver REAL y adoptar su solución** (`geophysics_service.py:2921-2989`). Es la respuesta correcta al riesgo de que un funcional proxy diverja del real — riesgo que el equipo detectó y rodeó conscientemente. Emite además advertencias explícitas (`morozov_underfit_floor`, `morozov_overfit_ceiling`) cuando no existe bracket de χ²=1, en vez de devolver un λ de borde fingiendo convergencia. **Verifiqué este diseño intentando refutarlo y no pude** (§9D.2).
10. **El criterio de σ explícito para habilitar Morozov** (`:2808-2818`): si el cliente declara ruido o gravímetro, χ² es interpretable y se usa la discrepancia; si no, se cae a un operating point fijo con justificación medida. Distinguir "tengo información para calibrar" de "no la tengo" es exactamente la honestidad que vende el producto.

---

# 9-BIS. ESTUDIOS INSTRUMENTADOS (2ª pasada)

*Añadido tras la primera entrega. Como la delegación en subagentes quedó bloqueada por presupuesto, esta segunda pasada usa un enfoque distinto y más barato: **scripts de análisis estático sobre el 100% del repositorio**. La ventaja no es solo el coste — es que producen evidencia **reproducible y verificable**, no opinión. Artefactos en `scratchpad/audit/study_*.py`.*

## 9B.0 Advertencia metodológica (y por qué la incluyo)

Mi primer script reportó **30 módulos huérfanos**. Eran casi todos falsos positivos, por tres bugs propios:

1. Excluí `main.py` del escaneo — y ahí se montan los 22 routers. → los 22 aparecían huérfanos.
2. Mi detector de endpoints buscaba `@router.` y los endpoints usan `@router_v2.` → 7 endpoints marcados como funciones muertas.
3. No contemplaba el patrón `from services import project_store` → 4 módulos más como falsos huérfanos.

Tras corregir: **30 → 7 → 1 huérfano real** (verificado uno por uno con grep).

**Lo incluyo deliberadamente.** Una auditoría que presenta salida de herramienta sin verificarla es peor que no auditar: genera trabajo destructivo sobre código sano. Todo lo que sigue está verificado individualmente.

## 9B.1 [H-9] Duplicación estructural entre los dos motores de física 🟠

**Método:** normalización de tokens (se eliminan comentarios, docstrings, literales y nombres de identificadores; se conserva la estructura), ventanas deslizantes de 12 líneas, huella criptográfica. Detecta copy-paste aunque cambien los nombres.

**[MEDIDO]** Sobre 114 archivos y 32.091 ventanas únicas:

| Ventanas duplicadas | Archivos implicados |
|---:|---|
| **228** | `exploration/gravimetry.py` ↔ `exploration/magnetometry.py` |
| 60 | `magnetometry.py` consigo mismo (p.ej. 1036-1047 ≡ 1069-1080) |
| 44 | `api/gravity_import_api.py` consigo mismo (570-583 ≡ 838-850 ≡ 2054-2067) |
| 34 | `gravimetry.py` consigo mismo (1343-1357 ≡ 3331-3343) |
| 25 | `core/block_model_store.py` (137-150 ≡ 593-604 ≡ 624-635) |
| 20 | `services/coordinate_transform_service.py` (158-171 ≡ 211-224) |
| 15 | `services/spatial_readiness_service.py` (4 repeticiones) |

**Verificación de un caso concreto:** `gravimetry.py:74` y `magnetometry.py:74` definen ambos `_sigma_adaptive` con la misma lógica, mismos umbrales (MAD, 3·1,4826, downweight 10×, percentiles p5–p95) y las mismas referencias. El docstring de magnetometría **lo admite explícitamente**: *"port de gravimetry Fase 18"*, *"idéntico en forma al de gravimetry"*.

**El matiz que lo hace accionable:** ya existe `exploration/geophysics_weights.py` — el módulo compartido correcto. Pero tiene **65 líneas y solo 3 funciones** (`sigma_parametric`, `apparent_susceptibility`, `true_susceptibility`). **La extracción se empezó bien y se abandonó a un 3% del camino.** No hay que inventar una arquitectura: hay que terminar la que ya se eligió.

**[INFERENCIA]** Coste real de esta duplicación: cada corrección de física en gravimetría debe replicarse a mano en magnetometría. El propio hallazgo H-1 de esta auditoría (`W_z` inerte) **existe por duplicado**: `magnetometry.py:840` (`solve_magnetic_inversion_lsqr`, 840 LOC, 37 args) reproduce la misma cadena `Wz→Ws`. **Arreglar H-1 significa arreglarlo dos veces**, o extraer primero.

## 9B.2 [H-10] La fase F7 completa no tiene interfaz de usuario 🟠

**Método:** inventario de los 60 endpoints declarados (parseando decoradores y prefijos de `APIRouter`) cruzado con todo el texto de `app/`, `lib/`, `componentes/` y `store/` del frontend.

**[MEDIDO]** 10 de 60 endpoints no tienen rastro en el frontend:

| Endpoint | Ubicación | Interpretación |
|---|---|---|
| `GET /license/status` | `license_api.py:21` | **F7** |
| `POST /license/activate` | `license_api.py:27` | **F7** |
| `GET /diagnostics/manifest` | `diagnostics_api.py:17` | **F7** |
| `GET /diagnostics/export` | `diagnostics_api.py:24` | **F7** |
| `GET /system/connectivity` | `system_api.py:63` | **F7** |
| `GET /v2/block-model-profile` | `block_model_api.py:281` | ya declarado en `docs/03` → F4/F5 |
| `GET /borehole/lithology-properties` | `borehole_api.py:228` | ya declarado → F4 |
| `POST /geophysics-live-update` | `geophysics_api.py:193` | ya declarado → F11 |
| `POST /v2/gravity-import/invert-with-corrections` | `gravity_import_api.py:674` | ya declarado → F2B/F3 |
| `GET /projects/{id}/satellite-indices` | `spectral_api.py:10` | GEE secundario |

**Los 5 últimos ya estaban inventariados honestamente en `docs/03_MAPA_CODIGO.md` §5** — el mapa del proyecto es fiable. **Los 5 primeros no.**

**El hallazgo:** `docs/01_PLAN_MAESTRO.md` declara F7 con *"gate `f7_gate_packaging.py` PASS 30/30"* y *"29 tests F7 verdes"*. Es cierto **a nivel de backend**. Pero **un usuario no puede activar una licencia, ni exportar un diagnóstico, ni ver si está offline** — no hay UI que llame a esos endpoints. Un gate de backend en verde se leyó como fase entregada.

**[OPINIÓN]** Esto no es deshonestidad: es un gate mal especificado. El criterio de salida medía el backend, no el camino del usuario. **Recomendación de proceso, más valiosa que el hallazgo:** todo gate de fase debe incluir un criterio *"un usuario puede hacer X desde la UI"*, no solo *"el endpoint responde"*.

## 9B.3 [H-11] 29 de 44 variables de entorno nunca se ejercitan 🟡

**[MEDIDO]** Inventario completo de `os.getenv`/`os.environ` en producción, tests y scripts:

- **44** variables de entorno distintas.
- **29 (66%) nunca aparecen en ningún test ni script.**
- Entre ellas, **todas las que controlan el solver numérico**: `USE_SPARSE_DIRECT`, `USE_BOUNDED_SOLVER`, `USE_LSMR_LARGE`, `USE_PROJECTED_SOLVER`, `LSMR_THRESHOLD_N_ACTIVE`, `USE_WAVELET_COMPRESSION`, `WAVELET_THRESHOLD_N_ACTIVE`, `ENABLE_FOCUSING`.
- Y todas las de licenciamiento y despliegue: `TQ_LICENSE`, `TQ_LICENSE_PUBLIC_KEY_HEX`, `TQ_MASTER_KEY`, `TQ_AUTH_ENABLED`, `TQ_FREE_MAX_VOXELS`, `CORS_ALLOWED_ORIGINS`, `CSV_MAX_BYTES`, `TERRAQUANTUM_HOST/PORT`.

**Esta es la causa raíz sistémica de H-2.** El símbolo inexistente `solve_sparse_normal_equations` sobrevivió no por descuido puntual, sino porque **existe una clase entera de configuración que ningún test toca**. Contrasta de forma llamativa con la disciplina del resto: el proyecto escribió un fuzzer propio, 10.000 casos generativos de ingesta y una prueba de degradación de kernel — pero nadie prueba `USE_SPARSE_DIRECT=true`.

**Interpretación honesta:** `TQ_AUTH_ENABLED` está documentado en `docs/03` §6.3 como *"rompería la UI si se activa"*. **Es un flag conocido-roto en producción, sin test que lo declare.** Un cliente que siga la documentación de despliegue y lo active, rompe su instalación.

## 9B.4 [H-12] `core/storage.py`: generalidad especulativa 🟡

**[MEDIDO]** Único módulo huérfano real tras verificación: 168 líneas, `StorageBackend` abstracto + `LocalStorageBackend` + `_S3StorageBackend` y `_GCSStorageBackend` que lanzan `NotImplementedError`. **Cero importadores** en producción, tests o scripts. La única mención en todo el repositorio es un **comentario** en `core/config.py:127`.

**[OPINIÓN]** Es el ejemplo de manual de *speculative generality*: una abstracción de tres backends construida para una nube que el producto **rechazó explícitamente por estrategia** (`docs/02_PRODUCTO.md` §6: *"NO es una plataforma cloud multi-tenant"*). Borrarla no tiene riesgo y elimina una señal confusa sobre hacia dónde va la arquitectura.

## 9B.5 Símbolos públicos sin referencia y cobertura de tests

**[MEDIDO] 16 funciones/clases públicas** definidas y jamás referenciadas en todo el repositorio (excluyendo endpoints). Destacables por su significado:

| Símbolo | Ubicación | Comentario |
|---|---|---|
| `solve_inversion_lsmr_wavelet` | `solver_preconditioned.py:326` | Compresión wavelet del Jacobiano (Farquharson & Oldenburg 2003) — construida, nunca llamada |
| `remove_regional_scale` | `preprocessing.py:363` | Coherente con "regional refutada" (hallazgo medido); es un cadáver de experimento |
| `build_gradient_operators_from_mesh` | `geophysics_math.py:155` | Operadores de gradiente sin consumidor |
| `export_core_to_gslib` | `export_service.py:535` | Exportador construido sin cablear |
| `configure_logging` | `core/logging.py:6` | **Sospechoso**: sugiere que el logging no se configura centralmente |
| `resolve_mine_design_block_model_reference` | `block_model_store.py:801` | Vestigio del módulo de diseño minero (anti-scope) |

**[MEDIDO] Cobertura de tests por módulo:** 204 archivos de test importan módulos de producción; **25 módulos (3.893 LOC, 8,0% del backend) no son importados por ningún test.** Los más grandes: `spectral_service` (632), `gravity_corrections_api` (453), `block_model_api` (307), `license_service` (306), `borehole_api` (257).

*Caveat metodológico:* los routers suelen probarse vía `TestClient` sin importarse. Verifiqué: **119 archivos de test usan `TestClient`**, pero las rutas `/keys*`, `/favorability*`, `/report*` y `/metrics*` **tienen 0 ejercicio HTTP**. Esto **corrobora exactamente** lo que `docs/03_MAPA_CODIGO.md` §6.5 ya declaraba (*"cobertura de tests HTTP inexistente en borehole_api, chat_api, export_api, keys_api, favorability"*). El autoinventario del proyecto es preciso.

Del otro lado, la concentración de esfuerzo es correcta: `exploration/gravimetry` (65 archivos de test), `api/gravity_import_api` (58), `services/geophysics_service` (48). **Lo crítico está fuertemente cubierto.**

## 9B.6 Dependencias muertas y peso del instalador

**[MEDIDO]** 32 dependencias declaradas en `requirements.txt`. Tras verificar una por una las candidatas (corrigiendo mis propios alias erróneos: `PyWavelets`→`pywt` con 1 uso y `earthengine-api`→`ee` con 5 usos **sí se usan**):

| Dependencia | Imports en producción | Veredicto |
|---|---:|---|
| `distributed` | **0** | **Muerta.** Dask distribuido; solo se usa `dask` simple con scheduler síncrono |
| `shapely` | **0** | **Muerta** |
| `python-multipart` | 0 | **Legítima**: FastAPI la exige para `Form`/`File`. No tocar |
| `uvicorn`, `pytest`, `pytest-cov` | 0 | **Legítimas**: runners |
| exportadores OpenTelemetry | 0 | Plugins; coherentes con `OTEL_ENABLED` |

**[INFERENCIA]** Relevancia concreta: el sidecar PyInstaller pesa **199 MB** y el instalador **322 MB**. `shapely` (con GEOS) y `distributed` (con tornado, msgpack, cloudpickle) son dependencias pesadas. Quitarlas es una reducción de tamaño **gratuita y sin riesgo**, y el tamaño importa en un producto que se descarga e instala en máquinas de consultores.

## 9B.7 [H-15] El default de escucha es `0.0.0.0` — trampa latente, no vulnerabilidad activa 🟡

Este hallazgo es un buen ejemplo de por qué una auditoría debe medir antes de alarmar. La secuencia real:

**[HECHO]** `core/config.py:47`: `BACKEND_HOST = os.getenv("TERRAQUANTUM_HOST", "0.0.0.0")`. El valor por defecto expone el backend en **todas las interfaces de red**. Y `main.py:248` lo usa directamente en `uvicorn.run`.

En un producto cuya promesa central es *"los datos del cliente jamás salen de su máquina"* (`docs/02_PRODUCTO.md` §4.4), y cuya API tiene `TQ_AUTH_ENABLED=false` por defecto, eso sonaría a hallazgo crítico. **No lo es.** Verifiqué los cuatro caminos de arranque:

| Camino de arranque | Host efectivo | Evidencia |
|---|---|---|
| Instalador Tauri (**el producto real**) | `127.0.0.1` ✅ | `src-tauri/src/lib.rs:111` fija `TERRAQUANTUM_HOST=127.0.0.1`; y `:135` fija `HOSTNAME=127.0.0.1` para el sidecar Node |
| `start-backend.bat` | `127.0.0.1` ✅ | `:29` pasa `--host 127.0.0.1` explícito |
| `run_terraquantum_desktop.ps1` (Plan B) | `127.0.0.1` ✅ | `:53` |
| Docker | `0.0.0.0` ✅ **correcto** | `docker-compose.yml:11` lo fija explícito; dentro de un contenedor es **obligatorio** para que funcione el mapeo de puertos |

**Conclusión honesta: el producto que se instala en la máquina del cliente está bien.** El default inseguro existe por el camino Docker, donde es la elección correcta.

**Pero sigue siendo un hallazgo**, por tres razones acumulativas:
1. La seguridad depende de que **tres lanzadores distintos** recuerden sobreescribir el valor. Un cuarto lanzador futuro, o un `python main.py` de diagnóstico en la máquina del cliente, expone una API **sin autenticación** en la red del sitio minero o del hotel.
2. `TERRAQUANTUM_HOST` es una de las **29 variables que ningún test ejercita** (H-11). Nada detectaría la regresión.
3. `TQ_AUTH_ENABLED` está documentado como *"rompería la UI si se activa"*: no hay una segunda línea de defensa.

**Recomendación de coste cero:** invertir el default a `127.0.0.1`. **No rompe nada**, porque `docker-compose.yml:11` **ya fija `0.0.0.0` explícitamente**. El camino que necesita exposición la pide; los demás quedan seguros por construcción. Es el principio de *secure by default* aplicado con una línea.

## 9B.8 [H-16] El frontend concentra complejidad **más** que el backend

**[MEDIDO]** Sobre 128 archivos TS/TSX y 28.131 líneas:

| LOC | useState | useEffect | useMemo | store | Archivo |
|---:|---:|---:|---:|---:|---|
| 2.724 | 0 | 0 | 0 | 0 | `lib/terraquantum/frontendApi.ts` |
| 2.085 | 3 | 9 | 16 | 20 | `componentes/Scene3D.tsx` |
| **1.953** | **41** | 2 | 3 | 3 | `componentes/PrepPanel.tsx` |
| 1.216 | 17 | 0 | 1 | 0 | `componentes/PrepEnrichPanel.tsx` |
| 942 | 16 | 1 | 1 | 0 | `componentes/GravityCorrectionWizard.tsx` |
| 879 | 2 | 2 | 1 | 6 | `componentes/views/Exploration3DView.tsx` |
| 804 | 0 | 0 | 0 | 0 | `store/useAppStore.ts` |

**Dos números que importan:**

1. **8 archivos (>700 LOC) concentran el 40,2% del frontend** — una concentración **peor** que la del backend (26,4%). El diagnóstico de "espina dorsal sobrecargada" (H-3) no es exclusivo del backend; es un patrón del proyecto entero.
2. **`PrepPanel.tsx` tiene 41 `useState` en un solo componente** — el 24% de todo el estado local del frontend (173 `useState` en total) vive en un archivo. **[OPINIÓN]** Con 41 piezas de estado independientes, el número de combinaciones alcanzables es intratable de razonar y de testear; los bugs de este tipo de componente son siempre "en cierta secuencia de clics queda inconsistente". Es el candidato número uno a `useReducer` o a una máquina de estados explícita.

**[INFERENCIA]** Que `PrepPanel` sea el peor no es casualidad: es el panel del **paso más valioso del producto** (la preparación que trabaja, F2/F2B). El valor y la complejidad crecieron juntos, igual que en `run_geophysics_inversion`.

### La contracara: una decisión arquitectónica que la medición **valida**

**[MEDIDO]** De los **40 proxies** de `app/api`: **29 transforman de verdad** (marshaling de `FormData`/`Buffer`, reempaquetado JSON, ramificación condicional) y solo **11 son tubería fina**. Los 7 más cargados son toda la cadena de ingesta (`build-package`, `enrich-package`, `parse-rows`, `analyze-columns`, `export-clean-csv`, `borehole/parse-file`, `load-package`).

Esto **confirma con números** la decisión registrada en `docs/01_PLAN_MAESTRO.md` F7: descartar `output:'export'` y empaquetar un sidecar Node para conservar los proxies, porque reescribirlos habría duplicado lógica. **La decisión era correcta y ahora está medida, no solo argumentada.** Es justo decirlo con la misma claridad con la que señalo los defectos.

*Matiz [OPINIÓN]:* que 29 proxies transformen es a la vez la justificación del sidecar **y** una señal de que parte de ese marshaling podría vivir en el backend, simplificando el empaque. No es urgente, pero es la pregunta correcta a hacerse antes de añadir el proxy número 41.

### Superficie de tipos y riesgo de divergencia

**[MEDIDO]** 284 declaraciones de `interface`/`type`, 216 nombres distintos, **40 nombres declarados más de una vez**. Los relevantes son los que replican contratos del backend: `BackendVoxelModel` (4 declaraciones), `SniffReport` (3), `BuildPackageConfig` (3), `VoxelMineralModel` (2).

**[INFERENCIA]** Cada una de esas declaraciones es una copia manual de un esquema Pydantic. Nada garantiza que sigan coincidiendo: si el backend añade un campo a `SniffReport`, hay tres sitios que actualizar en el frontend y ningún test que falle si se olvida uno. **Recomendación de bajo coste:** generar los tipos del frontend desde el OpenAPI que FastAPI ya expone (`openapi-typescript`), al menos para los contratos del camino dorado. Elimina la clase entera de bug.

## 9B.9 Resumen de la 2ª pasada

| # | Hallazgo | Severidad | Método |
|---|---|---|---|
| H-9 | 228 ventanas duplicadas gravimetría↔magnetometría; extracción compartida abandonada al 3% | 🟠 Alto | Huella de tokens normalizada |
| H-10 | F7 (licencias, diagnóstico, conectividad) sin ninguna UI: 5 endpoints huérfanos | 🟠 Alto | Cruce endpoints↔frontend |
| H-11 | 29/44 variables de entorno nunca ejercitadas — causa raíz sistémica de H-2 | 🟡 Medio | Inventario de `os.getenv` |
| H-12 | `core/storage.py` huérfano: abstracción S3/GCS para una nube rechazada por estrategia | 🟡 Medio | Grafo de imports verificado |
| H-13 | 16 símbolos públicos sin referencia; 8% del backend sin test que lo importe | 🟡 Medio | AST + cruce de referencias |
| H-14 | `distributed` y `shapely` declaradas y no usadas (peso del instalador) | 🟢 Bajo | requirements vs imports |
| H-15 | Default de escucha `0.0.0.0`. Los 4 caminos de arranque lo corrigen — pero por convención, no por construcción, y sin test | 🟡 Medio | Verificación de los 4 lanzadores |
| H-16 | 8 archivos = 40,2% del frontend; `PrepPanel.tsx` con **41 `useState`**; 40 nombres de tipo duplicados que replican esquemas Pydantic sin garantía de sincronía | 🟠 Alto | Métricas de complejidad frontend |

---

# 9-TER. EMPAQUE Y CALIDAD REAL DE LOS TESTS (3ª pasada)

*Las dos áreas que la 1ª pasada dejó como "cobertura parcial", auditadas por dos agentes especializados. **Verifiqué personalmente los cuatro hallazgos de mayor severidad** antes de incorporarlos; lo indico en cada uno.*

## 9C.1 [H-17] Si un sidecar no arranca, el usuario ve un splash infinito 🔴 CRÍTICO

**[HECHO]** La cadena de arranque del instalador tiene un agujero completo de manejo de errores:

- `src-tauri/src/lib.rs:100-150` — `start_sidecars` retorna `Err` si falla el spawn del backend (y nunca llega a intentar el frontend).
- `lib.rs:177-181` — ese `Err` se absorbe **solo con `log::error!`**. No hay UI, no hay reintento.
- `lib.rs:184-197` — solo se espera al puerto del **frontend**. **Nunca se hace health-check del backend.**
- `src-tauri/splash/index.html:15-26` — el splash es HTML estático con una barra de progreso que **loopea para siempre** y un mensaje fijo. No hay JS que escuche ningún error.

**Por qué es crítico y no cosmético:** el escenario más probable de fallo en casa de un cliente es que un antivirus corporativo ponga en cuarentena un ejecutable PyInstaller de 199 MB sin firma de código. El resultado que ve el consultor es **una animación de carga elegante, para siempre**, sin saber que algo falló ni dónde buscar evidencia. Para un producto local-first vendido a terceros, donde no hay consola ni desarrollador presente, **este es el peor modo de fallo posible**: indistinguible de "es lento".

**[OPINIÓN]** Es el hallazgo más grave de toda la auditoría desde el punto de vista comercial. H-1 afecta a la calidad del resultado científico; H-17 impide que el producto arranque y no lo dice. Contradice frontalmente el principio de producto ya establecido en `docs/02_PRODUCTO.md` §4.1 (*"Ningún input produce crash ni basura silenciosa… siempre error en español que dice qué hacer"*): esa disciplina se aplicó con rigor al pipeline de datos y **no se aplicó al arranque de la aplicación**.

## 9C.2 [H-18] Sin Job Object: un cierre forzado deja procesos huérfanos que bloquean el siguiente arranque 🔴

**[MEDIDO — verificado por mí]** `grep -c "JobObject|CreateJobObject" src-tauri/src/lib.rs` → **0**.

`lib.rs:203-212` mata los PIDs con `taskkill /F /T`, pero **solo dentro de `RunEvent::Exit`** — es decir, solo en un cierre ordenado del bucle de Tauri. No hay `CreateJobObject`/`AssignProcessToJobObject`, que es el mecanismo de Windows para atar el ciclo de vida de los hijos al del padre.

**La cadena de fallo compuesta es lo que lo hace grave:** H-17 produce un splash infinito → el usuario hace lo natural y mata la app desde el Administrador de Tareas → `RunEvent::Exit` nunca se dispara → `backend.exe` y `node.exe` quedan vivos ocupando 8010 y 3000 → **el siguiente arranque falla también**, y por H-19 tampoco lo detecta.

## 9C.3 [H-19] `wait_for_port` no distingue el sidecar propio de un zombi ajeno 🟠

**[HECHO]** `lib.rs:89-98` — `wait_for_port` hace `TcpStream::connect` y da por bueno cualquier listener. `lib.rs:186-196` navega la ventana a `localhost:3000` en cuanto algo responde ahí.

Si el puerto está ocupado (por un zombi propio de H-18, o por otra aplicación del usuario), el sidecar nuevo falla su `bind` en silencio y **la ventana navega igual hacia lo que sea que esté escuchando**. Es un fallo de identidad, no de disponibilidad. El arreglo estándar es barato: que el health-check pida `/health` y valide una firma propia (versión + un token generado al arrancar), en vez de conformarse con un `connect`.

## 9C.4 [H-20] El updater está firmado, pero nada lo invoca — es un mecanismo de papel 🟠

**[MEDIDO — verificado por mí]** `grep -rn "plugin-updater|checkUpdate|check()"` sobre `src-tauri/src/*.rs` y `package.json` → **sin resultados**.

`tauri.conf.json:29-40` configura clave pública, endpoints y `createUpdaterArtifacts`, y los `.sig` se producen de verdad. Pero `@tauri-apps/plugin-updater` **no es dependencia** del `package.json` (solo está el CLI de build), y `lib.rs:176` registra el builder del plugin **sin llamar nunca a `.check()`**.

**Consecuencia:** el pipeline de firma funciona y el usuario **nunca verá un aviso de actualización**. `docs/04` describe cómo publicar una actualización sin aclarar que el lado del consumo no está cableado. Es el mismo patrón que H-10 (F7 sin UI): **backend/infraestructura lista, camino del usuario ausente, gate declarado en verde.** Que el patrón se repita dos veces en fases distintas sugiere que no es un descuido puntual sino la forma del criterio de cierre.

> **Cierre en dos tiempos, y el segundo destapó que el primero no bastaba (Fase 28, 2026-09-06).**
> La Fase 2 cableó `check()` y dio H-20 por cerrado. Medido un mes después: la
> llamada existía, **pero el único desenlace alcanzable era un error**, porque el
> endpoint apuntaba a `TerraQuantum/terraquantum`. Esta sección lo llamó
> «repositorio inexistente»; es peor y más concreto: `api.github.com/users/TerraQuantum`
> devuelve **200** — es la cuenta de un **tercero real** (id 90737998). Lo que
> protegía al usuario de instalar algo ajeno no era la URL sino la **firma
> minisign**, que es exactamente la defensa que se diseñó para eso.
>
> Y el aviso mentía sobre la causa: el 404 llegaba como `Error::ReleaseNotFound`
> —distinguible de un fallo de red— y se presentaba como «si no tienes internet
> es lo esperable», con el texto del crate **en inglés** incrustado. Es decir:
> **el mismo patrón que esta sección denuncia, una capa más adentro.** El gate de
> la Fase 2 dio verde porque comprobaba que la comprobación *ocurría*, no que
> *dijera la verdad*. Detalle completo y las cinco categorías nuevas en
> `docs/04` §6.1.

## 9C.5 [H-21] El navegador llama directo al backend: los 40 proxies no son la única puerta 🟠

**[MEDIDO — verificado por mí]** `lib/terraquantum/frontendApi.ts:7-10` define `BACKEND_PUBLIC_URL` a partir de `NEXT_PUBLIC_TERRAQUANTUM_BACKEND_URL` — el prefijo `NEXT_PUBLIC_` **expone la variable al navegador por diseño de Next.js**. Se usa en al menos tres llamadas de cliente: `:838` (URL del bundle de exportación), `:845` (DELETE de una corrida) y `:1955` (footprint).

**Esto matiza lo que escribí en §9B.8.** Sigue siendo cierto que 29 de 40 proxies transforman de verdad y que por tanto el sidecar Node estaba justificado. Pero **la premisa "todo pasa por los proxies" no se cumple al 100%**, y eso tiene una consecuencia de seguridad concreta: combinado con `TQ_AUTH_ENABLED=false` por defecto (`main.py:92-97`, `core/config.py:144`, y `lib.rs:108-112` nunca lo activa), **el binding a loopback y CORS dejan de ser defensa redundante y pasan a ser la única defensa real** entre cualquier proceso o pestaña de la máquina y un motor de inversión sin autenticar.

Esto **eleva la importancia de H-15**: invertir el default de `0.0.0.0` a `127.0.0.1` ya no es solo higiene, es la barrera que queda.

## 9C.6 [H-22] Calidad real de los tests: el activo es real, pero el 66% de los "gates" no decide nada 🟠

Esta es la parte que más me interesaba y el resultado es de dos caras.

**La cara buena — los oráculos son genuinos.** Enumerados y verificados: esfera analítica de forma cerrada (`test_sphere_forward.py`, `test_analytic_sphere_validation.py`), prisma contra la fórmula de **Plouff (1976)** (`test_prism_recovery_benchmark.py`), regresión física contra los 4 benchmarks con χ²∈[0.7,1.3] y misfit ≤3% (`f9_regression_lib.py` + `f9_gate_regression.py`), anti-inverse-crime real (malla forward 5 m vs inversión 15 m), ingesta generativa contra verdad del generador, y los tres tests de la trilogía honesta B1/B2/B3. **Comparar contra verdad independiente es exactamente lo que el informe 13 exige y lo que casi ningún proyecto de este tamaño hace.**

También: **cero dependencias de red y cero rutas absolutas** en los tests — buena señal de portabilidad. Y las tolerancias están **justificadas con la medición que las produjo** (p. ej. `san_nicolas_misfit_max_pct: 3.0 # medido 1.51% → margen ~2×`), no ajustadas hasta que pasara.

**La cara mala — [MEDIDO, verificado por mí con un conteo independiente]:** de los **65 scripts de `scripts/validation/`, 43 (66%) no contienen ningún `assert` ni código de salida `exit(1)`**. Son **diagnósticos que imprimen y escriben JSON: el juicio de PASS/FALLO queda enteramente en manos de un humano que lea la salida.** (El agente contó 46/65 = 71% con un patrón algo distinto; mi conteo independiente da 43/65 = 66%. La conclusión no cambia.)

**Por qué importa:** el proyecto llama "gate medido" a estos scripts y cierra fases con ellos. Los que **sí** deciden (f2b, f3, f7, f8, f9 — 22 de 65) son gates reales y buenos. Pero dos tercios del directorio son instrumentos de diagnóstico, no puertas. **Un gate que requiere que alguien interprete la salida no protege contra regresiones**, porque dentro de seis meses nadie recordará qué número era aceptable.

**Veredicto de calidad sobre la muestra leída (24 archivos, sesgada hacia los más críticos):** ~54% fuertes, ~21% medios, ~17% decorativos. El propio auditor advierte —correctamente— que al ser una muestra sesgada hacia lo importante, **el porcentaje real en los ~180 archivos restantes será menor**; su extrapolación honesta es 30-40% fuertes. **[OPINIÓN]** Comparto la advertencia: es una estimación, no una medición, y así debe leerse.

## 9C.7 [H-23] Reproducibilidad del build: parcial 🟡

**[HECHO]** Lo bien hecho: `numpy`, `scipy`, `pyproj` y `polars` están **pineados exactos**, y por la razón correcta — determinismo numérico. Eso demuestra que la reproducibilidad se pensó donde más importa.

Lo que falta: `pyarrow`, `zarr`, `dask`, `distributed`, `PyWavelets`, `scikit-learn` y `scikit-image` usan `>=` sin techo ni lockfile; no existe `.python-version`, `runtime.txt` ni `pyproject.toml`; y **`pyinstaller` no está pineado en ningún archivo del repositorio** pese a ser la herramienta que produce el sidecar de 199 MB.

**[INFERENCIA]** Reconstruir hoy el instalador de la misma versión puede producir un binario distinto. Para un producto que se distribuye firmado y con updater, esa es una brecha de cadena de suministro real, aunque de probabilidad baja.

**Dato menor pero revelador:** `docs/04` documenta **253 MB** de instalador; el real medido es **321,5 MB**. La documentación envejece más rápido que el artefacto.

## 9C.8 [H-24] El diagnóstico exportable puede filtrar datos vía tracebacks 🟡

**[HECHO]** `core/diagnostics_buffer.py:1-31` almacena los últimos 2.000 caracteres del traceback **tal cual**, y `main.py` usa `traceback.format_exc()`, que incluye el mensaje de la excepción. `tests/test_f7_diagnostics.py` verifica que no viajen claves de configuración ni extensiones de archivo prohibidas — **pero no inspecciona los mensajes de excepción**.

En un pipeline de ingesta de CSV, lanzar `ValueError` con el valor de celda ofensivo en el mensaje es el patrón más natural del mundo. Ese fragmento viajaría dentro del ZIP "solo metadatos" que el consultor envía a soporte. La promesa de `docs/04` es absoluta (*"sin datos de survey"*); la implementación es *casi* absoluta. **La corrección es barata:** sanear el mensaje de excepción antes de bufferizarlo, y añadir un test que siembre un valor reconocible en un mensaje de error y verifique que no aparece en el ZIP — exactamente la técnica que ya usaron para los secretos.

---

# 9-QUATER. EL ORQUESTADOR: DOS AUTOCORRECCIONES Y UNA DEGRADACIÓN SILENCIOSA (4ª–5ª pasada)

*Esta sección nace de verificar una suposición que yo mismo había marcado como no verificada en §11.1 (*"`magnetometry.py`: asumido simétrico a gravimetría por H-9"*). Resultó falsa — y al comprobarlo apareció un hallazgo mayor que H-1.*

## 9D.1 Corrección de un error propio: H-1 **no** afecta a magnetometría

**[MEDIDO]** Conteo de normalización de columnas por motor:

| Motor | Ocurrencias de `col_norms`/`Ws` | `depth_beta` |
|---|---:|---|
| `exploration/gravimetry.py` | **58** | 2.0 — **inerte** (H-1) |
| `exploration/magnetometry.py` | **0** | 1.5 — **activo** |

**El propio código lo documenta** en `magnetometry.py:1862`: *"DIFERENCIA CLAVE con gravedad: el motor magnético NO tiene column scaling Ws; … (depth+z0)^{+β/2} (no por Ws)"*.

**Corrijo lo que escribí en §9B.1 y en la Fase 4:** afirmé que, por la duplicación H-9, *"arreglar H-1 significa arreglarlo dos veces"*. **Es falso.** El magnético nunca tuvo el problema: su depth-weighting **funciona**. La dependencia que puse entre la Fase 4 y la Fase 7 por este motivo queda anulada (la extracción compartida sigue justificada por H-9, pero no es prerrequisito de A).

**Y esto abre un confound científico que el proyecto debería conocer.** `docs/05` §Parte B midió que la magnetometría recupera profundidad mucho mejor que la gravedad (218 m frente a los 62 m apilados) y lo atribuyó **enteramente a la física**: *"porque su kernel cae más rápido (1/r³) y su estructura dipolar restringe la profundidad"*. Esa explicación es plausible y probablemente cierta en parte. Pero hay una **segunda explicación no controlada**: el motor magnético tiene un depth-weighting operativo y el gravimétrico no. **[INFERENCIA]** Separar ambas causas es barato y vale la pena: correr la gravedad con el depth-weighting reparado y ver cuánto del gap se cierra. Si se cierra mucho, parte de la conclusión "las físicas son complementarias" era un artefacto de implementación.

## 9D.2 [H-25 — **RECTIFICADO**] Dos selectores de λ obsoletos siguen invocables 🟡 MEDIO

> ### ⚠️ CORRECCIÓN IMPORTANTE DE ESTA AUDITORÍA
>
> **La primera versión de esta sección afirmaba que el λ de producción se calibra sobre un funcional distinto del que se resuelve, y lo clasificaba como CRÍTICO. Era incorrecto.** Al leer el orquestador (`services/geophysics_service.py`) —el paso siguiente de la auditoría— comprobé que la ruta de producción **no usa** el selector desalineado.
>
> **[MEDIDO]** `select_lambda_chi2_target` tiene **cero llamadores** en todo el repositorio: solo aparece en dos comentarios. `select_lambda_lcurve` se llama únicamente desde `tests/synthetic_recovery_benchmark.py:500`.
>
> **Lo que hace producción** (`geophysics_service.py:2921-2989`) es notablemente mejor: cuando σ es explícito, escanea 5 candidatos λ ∈ [0.01, 10] **ejecutando el solver real de producción** (`_solve_full_grid`), elige el de |log₁₀(χ²)| mínimo, hace una bisección geométrica extra si detecta bracket, y **adopta directamente la solución de ese solve** (`:2976`). No hay funcional proxy, luego no hay desajuste. Coste: ≈6 solves.
>
> **Y el equipo ya había diagnosticado exactamente lo que yo "descubrí"**, en el comentario `:2923-2925`: *"select_lambda_chi2_target (gravimetry.py) usa la maquinaria pre-W_z (column scaling viejo + sigma adaptivo hardcodeado) — su chi²(λ) no corresponde al operador actual"*. Lo detectaron y lo rodearon.
>
> **Mi reconstrucción de que "el bug regresó en silencio" era falsa.** No regresó: fue identificado y evitado. Dejo la corrección visible en lugar de borrar el error, porque un lector que solo viera la versión final no sabría que este punto fue examinado a fondo. **Y porque es la segunda vez en esta auditoría que verificar una hipótesis propia la refuta** (la primera fue magnetometría, §9D.1): eso dice algo sobre cuánta desconfianza merece el análisis estático sin lectura del camino real.

### Lo que sí queda, con su severidad correcta

**[HECHO]** `select_lambda_chi2_target` (≈180 líneas) y `select_lambda_lcurve` (≈257 líneas) permanecen en `gravimetry.py` con un χ²(λ) que, por reconocimiento propio del código, **no corresponde al operador actual**. El comentario `:2799` dice que el método *"permanece disponible en gravimetry.py para diagnóstico"*.

**[OPINIÓN] Un instrumento de diagnóstico que mide con el operador equivocado no es un instrumento: es una trampa.** Nada impide que alguien —el propio autor dentro de seis meses, o un colaborador futuro— lo llame para investigar un problema de regularización y obtenga números que parecen razonables y no lo son. No hay `DeprecationWarning`, ni assert, ni test que declare la incompatibilidad; solo un comentario a 1.300 líneas de distancia del punto de uso.

**Consecuencia concreta y medible:** `tests/synthetic_recovery_benchmark.py:500` **sí lo usa** (la variante L-curve). Es decir, **un benchmark del proyecto selecciona λ con maquinaria que no corresponde al solver de producción.** Cualquier conclusión de ese benchmark sobre regularización debe releerse con ese matiz.

**Recomendación:** borrar ambos selectores (la funcionalidad real vive en el orquestador), o si se quieren conservar como referencia histórica, moverlos a `experimental/` y hacer que lancen `NotImplementedError` con el motivo. Cierra la trampa sin perder el registro.

### Lo que hay que reconocer como excelente

El diseño del Morozov de producción **merece figurar entre las decisiones a mantener** (§9): escanear con el solver real y adoptar su solución es la respuesta honesta y correcta al problema de que un funcional proxy pueda divergir del real. Cuesta ~6 solves y elimina toda una clase de error. Además emite dos advertencias explícitas cuando el bracket de χ²=1 no existe (`morozov_underfit_floor` y `morozov_overfit_ceiling`, `:2963-2972`), en vez de devolver un λ de borde fingiendo que convergió. **Eso es exactamente la disciplina anti-corrupción-silenciosa que caracteriza al proyecto en su mejor versión.**

---

<details>
<summary><b>Texto original de esta sección (incorrecto), conservado para trazabilidad</b></summary>

*Afirmaba que el selector de λ de producción usaba `w_reg=(z+z₀)⁻²` mientras el solver usaba una penalización uniforme, con un ratio medido de 225×–900×, y que eso contaminaba la conclusión "Morozov es frágil en profundo" de `docs/05`. **La medición del ratio es correcta** (los dos funcionales del código efectivamente difieren en esa proporción); **la inferencia de que afecta a producción no lo es**, porque el selector desalineado no se ejecuta. La hipótesis de que la fragilidad de Morozov en profundo tenga causas de implementación queda **descartada por esta vía**; la explicación del null-space de `docs/05` §A′ se mantiene sin competencia.*

</details>

**[HECHO] El selector** `select_lambda_chi2_target` (`gravimetry.py:1547`, la ruta de **producción** cuando el cliente declara σ) construye su bloque de *smallness* así:

```python
# gravimetry.py:1641-1645
w_depth = (true_depth + z0) ** 2.0
w_reg   = 1.0 / w_depth
w_reg   = w_reg / np.mean(w_reg)      # depth weighting REAL, media 1
# :1671-1674
_w_sm = float(lam) * w_reg
_sb   = _sp.diags(_w_sm) @ Ws          # penalización PONDERADA POR PROFUNDIDAD
```

**[HECHO] El solver real** `solve_inversion_lsqr` construye el suyo así:

```python
# gravimetry.py:2417  (_mk_small)
w = np.full(_n_active_sol, lambda_mag_eff, dtype=np.float64)   # UNIFORME
```

Son **dos funcionales de regularización distintos**. El escáner penaliza las celdas someras mucho más que las profundas; el solve penaliza todas por igual.

**[MEDIDO] ¿Es la diferencia una constante absorbible en λ?** No. Medí la variación de `w_reg` en mallas del rango del producto:

| Malla | `w_reg` capa somera | `w_reg` capa profunda | Ratio |
|---|---:|---:|---:|
| 25 m × 20 capas | 12,53 | 0,0313 | **400×** |
| 50 m × 20 capas | 12,53 | 0,0313 | **400×** |
| 50 m × 30 capas | 18,61 | 0,0207 | **900×** |
| 100 m × 15 capas | 9,49 | 0,0422 | **225×** |

Si `w_reg` fuera constante, la discrepancia se absorbería en λ y sería inofensiva. **Varía entre 225× y 900×.** El λ que el escáner declara que produce χ²=1 se calibró contra una penalización 400 veces más fuerte arriba que abajo; el solve aplica una penalización plana. **El λ elegido no es el λ que el solver necesita.**

### La prueba de que esto ya se había detectado — y volvió

El comentario en `gravimetry.py:1664-1667` es la evidencia más contundente:

> *"H3b (causa J): el trial debe usar la MISMA smallness depth-weighted que `solve_inversion_lsqr` (tras H2): `diag(lam·w_reg)·Ws` con damp=0. Antes el core usaba `damp=lam` (smallness uniforme) → **el χ² del trial divergía ~700× del χ² real del solve, invalidando la calibración por chi²-target**."*

**[INFERENCIA, con alta confianza]** La secuencia reconstruida es: (1) se detectó que escáner y solver diferían y el χ² divergía ~700×; (2) se alineó el escáner al solver de entonces, que usaba smallness ponderada por profundidad; (3) más tarde, el cambio "H-A0 Bug 1 / W_z formal" reemplazó la smallness del solver por la identidad en `m̃`; (4) **nadie actualizó el escáner**. El bug que se arregló explícitamente **ha regresado en silencio**, por el mismo mecanismo que el comentario advierte.

### Por qué importa tanto

`docs/05` §A′ documenta como resultado central que **Morozov recupera el régimen moderado (12±0 m a 300 m) pero es frágil a 600 m (312±184 m) y falla a 900 m**, y atribuye la fragilidad al aplanamiento de la pendiente de χ²(λ) por el null-space — un mecanismo físico real y bien argumentado.

**[INFERENCIA] Pero hay una causa alternativa no controlada:** si el λ se selecciona contra un funcional distinto del que se resuelve, el χ² alcanzado por el solve **no será** el χ² que el escáner prometió, y el error crecerá con la profundidad — porque es justo en profundidad donde los dos funcionales más difieren (400× de ratio). **La "fragilidad de Morozov en profundo" podría ser, en parte, este desajuste y no solo el null-space.**

No afirmo que lo sea: afirmo que **es una hipótesis medible que hoy no está descartada**, y que el proyecto no podía verla porque el desajuste está repartido entre dos funciones separadas por 800 líneas.

**Verificación decisiva y barata** (una tarde): instrumentar una corrida para registrar el χ² que el escáner predice para el λ elegido y el χ² que el solve consigue con ese mismo λ. Si divergen, está confirmado. Es exactamente la medición que el comentario H3b describe haber hecho una vez.

## 9D.2-bis [H-27] La inversión puede caer a topografía PLANA sin que el usuario se entere 🟠 ALTO

**[HECHO]** En `geophysics_service.py:2789-2792` (ruta gravimétrica):

```python
except Exception as _topo_exc:
    _log.warning("topography_activation_nonfatal", error=str(_topo_exc))
    _topography_elevations_padded = None
    _topography_used = "flat_fallback"
```

Lo mismo en la ruta magnética (`:1946-1949` → `_topo_used_mag = "flat_fallback"`).

**Por qué esto no es un fallback benigno.** La topografía no es decoración: determina la **máscara de celdas activas** (qué vóxel es aire y cuál es roca) y la **profundidad verdadera de cada celda** (`true_depth = y_c − topo_depth`, `gravimetry.py:2197`). Caer a topografía plana en un survey de terreno montañoso —Laguna del Maule, los Andes, es decir **el caso de uso central del producto**— cambia la geometría del problema inverso. El resultado es un modelo que se ve válido, con su veredicto y su χ², **calculado sobre una geometría equivocada**.

Esto es exactamente lo que `docs/05` Parte C declara como enemigo número uno: *"el enemigo #1 NO es el crash — es el número corrupto con cara de bueno"*, y lo que `docs/02_PRODUCTO.md` §4.1 prohíbe: *"JAMÁS basura silenciosa con sello GOOD"*.

**[MEDIDO] ¿Llega al usuario?** No.

| Campo | Escrito por el backend | Leído por el frontend |
|---|---:|---:|
| `topography_used` | 1 (`:4306`, payload de la corrida) | **0** |
| `topography` (magnético) | 1 (`:2275`) | **0** |

**Y lo que lo hace fácil de corregir:** el canal ya existe. El backend emite arrays `warnings[]` (calidad de observación, favorabilidad, topes espaciales), el tipo `warnings: string[]` está en `frontendApi.ts` y `WarningBanner.tsx` los renderiza. **El fallback de topografía simplemente no los usa**: solo escribe en el log estructurado, que en una instalación de escritorio nadie lee. **La corrección es una línea** — añadir el aviso al array que ya viaja a la UI.

*Matiz honesto:* `WarningBanner` hoy solo se monta en `PrepPanel.tsx:1392` (preparación), no en la vista de resultados. Así que la corrección completa son dos: emitir el aviso y montarlo también donde se ven los resultados.

**[OPINIÓN] Este es el cuarto caso del mismo patrón** (tras H-10 F7 sin UI, H-20 updater sin invocar, H-17 arranque sin mensaje): **el backend hace lo honesto —registra la degradación con un motivo nombrado— y el camino del usuario se detiene ahí.** A esta altura ya no es una coincidencia: es una propiedad estructural del proyecto. La disciplina de honestidad está implementada en la frontera del backend y **sistemáticamente no cruza al frontend**.

## 9D.3 [H-26] Cuatro formulaciones de regularización conviven en el mismo motor

Sumando lo anterior, `gravimetry.py` contiene **tres** definiciones distintas del término de modelo:

| Dónde | Smallness efectiva en espacio físico | ¿Depth weighting? |
|---|---|---|
| `solve_inversion_lsqr:2417` (**el que se resuelve**) | `‖ m ⊙ ‖col(W_d·G)‖ ‖²` | Implícita por sensibilidad, no ajustable |
| `select_lambda_chi2_target:1671` (**Morozov**) | `‖ λ·w_reg ⊙ m ‖²`, `w_reg=(z+z₀)⁻²` | **Sí**, Li & Oldenburg explícito |
| `select_lambda_lcurve:1402` | `diag(w_reg)·Ws` | **Sí** |
| `magnetometry.py` | `(z+z₀)^{+β/2}` como cambio de variable sin `Ws` | **Sí**, activo |

**[OPINIÓN]** Ninguna de las cuatro es incorrecta *en sí misma*; lo incorrecto es que **coexistan sin que nadie las haya comparado**, y que la documentación (y los comentarios del propio código) describan una sola. Esto es la consecuencia directa y predecible de H-3: cuando la lógica crítica vive en funciones de 1.000 y 2.000 líneas, dos formulaciones pueden divergir durante meses sin que nadie lo note, porque nunca aparecen juntas en una pantalla.

**Recomendación:** una única función `build_model_weights(...)` compartida por el solver, los dos selectores de λ y el motor magnético. Es la pieza que debería nacer en la Fase 7. **Y un test que verifique la identidad que hoy nadie comprueba: el χ² predicho por el escáner para λ* debe coincidir con el χ² obtenido por el solve con λ*, dentro de una tolerancia medida.**

---

# 9-QUINQUIES. LÓGICA DEL FRONTEND (6ª pasada)

*Auditoría de la lógica —no de las métricas— de `PrepPanel`, `useAppStore`, `Scene3D`, `frontendApi` y las vistas. **Verifiqué personalmente los tres hallazgos altos**, eslabón por eslabón, antes de incorporarlos.*

## 9E.1 [H-28] El modelo 3D anterior sobrevive al cambio de CSV 🟠 ALTO

**[MEDIDO] Cadena completa verificada, los cuatro eslabones:**

1. `PrepPanel.tsx:533-549` (`handleFileGravimetryChange`) y `:552-566` (magnetometría) resetean 11 piezas de estado local y llaman `clearActiveRun()`. **Nunca llaman `setModel(null)` ni `setShow3D(false)`.**
2. `useAppStore.ts:466-492` (`clearActiveRun`) limpia `activeRun`, `terrainData`, favorabilidad, footprint, georef y `percentileStats` — **pero no toca `model` ni `show3D`**, que son estado aparte (`:496`).
3. `Exploration3DView.tsx:324` define `resetExplorationState`, que **sí** haría la limpieza completa.
4. **[MEDIDO]** `grep` de `resetExplorationState` en todo el repositorio: **una sola ocurrencia — su propia definición.** Nunca se invoca.

**El escenario reproducible:** cargar el CSV A → invertir → ver el modelo 3D → volver a Preparación → elegir el CSV B → navegar a la vista 3D sin pasar de nuevo por el panel de carga. **Se muestra el modelo de A, sin ninguna señal de que no corresponde a B.**

**[OPINIÓN] En una herramienta cuyo único propósito es decidir dónde perforar, mostrar el modelo del survey equivocado sin avisar es el peor bug posible que no sea un crash.** Es exactamente la categoría que `docs/05` Parte C define como enemigo número uno — *"el número corrupto con cara de bueno"*— aplicada al artefacto más caro del producto. Y la función que lo arregla ya está escrita: solo hay que llamarla.

## 9E.2 [H-29] El reconocimiento de riesgo espacial sobrevive al cambio de archivo 🟠 ALTO

Este lo encontré al verificar el anterior, y no estaba en el reporte del agente.

**[MEDIDO]** `PrepPanel.tsx:543-544` resetea `acknowledgeSpatialRisk` y `acknowledgeRegionalScale` en el manejador de **gravimetría**. El manejador de **magnetometría** (`:552-566`) **no los resetea**.

Y esos dos flags no son decorativos:
- `:1903-1905` — **habilitan el botón** de generar paquete cuando el backend exigió reconocimiento (`requires_user_acknowledgement === true`).
- `:958-959` — **se envían al backend** como `acknowledge_spatial_risk` y `acknowledge_regional_scale`.

**Escenario:** el usuario carga un archivo con riesgo espacial declarado, marca la casilla entendiendo ese riesgo concreto, luego sustituye el archivo de magnetometría. **El reconocimiento persiste y viaja al backend como si el usuario hubiera aceptado el riesgo de la nueva configuración.** Es una puerta de seguridad que se queda abierta.

**Segundo agujero del mismo gate [HECHO]:** `handleValidate` (`:568`) valida **un solo archivo**, el que corresponde a `dataType` (el último tocado), mientras que `handleGeneratePackage` (`:901-928`) arma el paquete con **ambos** archivos si están presentes. Si el último validado fue el bueno, el archivo problemático entra al paquete sin haber pasado el gate.

**[OPINIÓN]** Los dos agujeros comparten causa: el gate razona sobre "el archivo actual" mientras el paquete razona sobre "todos los archivos". Es el tipo de inconsistencia que 41 `useState` en un componente hacen casi inevitable (H-16), y el argumento más concreto a favor de la Fase 10.

## 9E.3 [H-30] Física derivada en el cliente: contraste de densidad con roca país fija 🟠 ALTO

**[HECHO]** `Scene3D.tsx:129-134`:

```ts
function getVoxelDensityAnomalyScore(cell: SceneCell) {
  const score = getCellNumber(cell, ["density_anomaly_score"], -999);
  if (score !== -999) return score;                    // el backend lo mandó: OK
  const dens = getVoxelModeledDensity(cell);
  return Math.max(0, dens - DENSITY_COUNTRY_ROCK_FALLBACK_T_M3) / DENSITY_COUNTRY_ROCK_FALLBACK_T_M3;
}
```

con `DENSITY_COUNTRY_ROCK_FALLBACK_T_M3 = 2.75` (`:91`), cuyo propio comentario admite: *"El backend debe proveer el valor específico del sitio"*.

**Por qué cuenta como violación de la frontera.** No es forward modeling, pero **el contraste de densidad respecto a la roca país es una cantidad física**, y 2,75 t/m³ (granodiorita) es una **suposición geológica del sitio**. En un survey sobre secuencias sedimentarias (~2,4) o rocas máficas (~2,9), ese contraste calculado en el cliente es incorrecto. Y no es cosmético: alimenta `getExplorationSupportScore` (`:397-403`), que se evalúa **para cada vóxel** (`:725-732`) y decide **qué se muestra** cuando el modelo es degenerado (`terraQuantumGeology.ts:537`).

Es decir: **justo cuando el modelo es débil —el escenario donde el usuario más necesita honestidad— el frontend decide con una fórmula y una densidad de referencia propias qué parte del cuerpo se ve como "el objetivo".**

**[HECHO] Los pesos también son inventados en el cliente:** `Math.max(probability·0.45, visualScore·0.45, densityAnomalyScore·0.10)` (`:402`). No hay trazabilidad de por qué 0,45/0,45/0,10.

**Lo que en cambio SÍ defiendo como legítimo** (y sería injusto no decirlo): los umbrales de visualización de `terraQuantumGeology.ts:146-156` (`ANOMALY_CONTRAST_VISIBLE=0.18`, `ANOMALY_PEAK_FRACTION=0.20`, `ANOMALY_WEAK_PEAK=0.60`) están **documentados con su razonamiento**, no cambian el modelo físico y son decisiones de política de render — que es exactamente lo que el frontend debe decidir. El propio `weakAnomaly` existe para que *"el usuario nunca confunda «no corrió» con «corrió débil»"*. Eso es buena ingeniería. La línea correcta no es "cero números en el frontend": es **"cero cantidades físicas derivadas en el frontend"**, y `getVoxelDensityAnomalyScore` la cruza.

## 9E.4 [H-31] `geophysicsModel.ts`: coordenadas geográficas fabricadas — código muerto 🟡

**[HECHO]** `lib/terraquantum/geophysicsModel.ts:277-314` construye coordenadas geográficas así: `x = lat + normalizedX * 0.02`, `y = lon + normalizedZ * 0.02` — un factor de 0,02° arbitrario **en lugar de una transformación geodésica**. Además fija malla y regularización en el cliente (`:156-172`: `lambda_mag=0.00005`, `alpha_spatial=1.5`) y define densidades "DEMO ONLY" (`:6-7`).

**[MEDIDO]** Solo se importa en `Exploration3DView.tsx:26-31` y **nunca se invoca** en el cuerpo; el otro consumidor (`frontendApi.ts:1`) importa únicamente el tipo. **Es inalcanzable: no engaña a nadie hoy.**

**[OPINIÓN]** Pero es la tercera pieza de física muerta en el frontend (con `engine-physics.ts` de H-6), y esta fabrica ubicaciones en el mapa. Una reconexión accidental produciría un modelo georreferenciado con coordenadas inventadas. **Borrar, no congelar.** Va a la Fase 6. — **✅ BORRADO el 2026-08-09** (`geophysicsModel.ts`, con los otros 7 archivos de H-6/H-31); verificado sobre el índice de git el 2026-08-14: ninguno ha vuelto.

## 9E.5 [H-32] Un `catch` que solo hace `console.warn` deja al usuario sin señal 🟡

**[HECHO]** `Exploration3DView.tsx:498-500`, dentro de `reloadBlockModelForMode()` (`:442-505`), que se dispara al cambiar el modo de datos o el nivel de LOD sobre un modelo ya cargado. Si la petición falla, el spinner se apaga y el modelo queda como estaba, **sin banner ni modal**. El usuario pulsa un botón y "no pasa nada".

Es la **única** ruta de recarga que no usa el patrón `TQErrorView`/`ErrorModal` ya establecido en el resto de la aplicación — lo que confirma que el patrón existe y es bueno, y que esto es un olvido puntual y no un vacío de diseño.

## 9E.6 Lo que el frontend hace bien (verificado, no cortesía)

- **[HECHO]** `fetchInternalJson` y el contrato `errorContract.ts` **nunca se tragan errores**: cada fallo se convierte en un `TQErrorView` tipado que llega al usuario. El catálogo de 60 errores en español funciona de verdad.
- **[HECHO]** `packageInversion.ts` está bien diseñado: abandono limpio al desmontar (sin cancelar la corrida del backend, que es lo correcto), cancelación explícita cuando el usuario la pide, y techo de reintentos si el backend cae. **No se hallaron fugas de timers ni de listeners** — algo poco común en código de polling.
- **[HECHO]** `Scene3D.tsx:602-605` libera geometría y materiales explícitamente al reemplazar la malla.

## 9E.7 Nota de método sobre esta pasada

El agente que auditó el frontend acertó en lo esencial y aportó dos hallazgos que yo no habría encontrado sin leer 5.000 líneas. Pero **verificar sus afirmaciones no fue ceremonial**: al comprobar H-28 encontré H-29 (el reconocimiento de riesgo que persiste), que el agente no reportó; y matizar H-30 exigió distinguir *cantidad física derivada* de *política de render*, distinción que el reporte original no hacía y que cambia qué hay que arreglar. **La delegación multiplica la cobertura; no sustituye el juicio.**

*(El segundo agente de esta pasada —árboles de conocimiento de los informes 04, 07, 12 y 13— volvió a caer por el límite de gasto de la cuenta. Es el tercer intento fallido sobre esa tarea; queda como el pendiente principal, junto al cuerpo de `magnetometry.py`.)*

---

# 9-SEXIES. INFORME 04: MOTORES OPEN SOURCE Y LA DECISIÓN COMPRAR-VS-CONSTRUIR (7ª pasada)

*El informe más largo del corpus (13.492 palabras) y el que más directamente informa decisiones de arquitectura. Tres intentos de delegarlo fallaron por presupuesto; lo leí yo. **Es también el que obliga a una advertencia sobre la calidad de la fuente.***

## 9F.0 Advertencia sobre la fuente

**[HECHO]** Los módulos 1–15 del informe 04 son de calidad alta: análisis técnico concreto y verificable de FreeCAD, Blender, OCCT/OCAF, VTK/ParaView, QGIS y CGAL, con nombres de clases reales (`TopoDS_Shape`, `TDF_Label`, `vtkAlgorithm`, `QgsMapRendererJob`, `BMesh`, `DepsGraph`).

**Los módulos 16 y 17 —justamente los de conclusiones y recomendaciones— degeneran.** Frases de 300 palabras con acumulación de adjetivos vacíos ("paramétrico asíncrono transaccional iterativo estandarizado orgánico...") que envuelven una idea de una línea. Un párrafo del módulo 16 usa la palabra "paramétrico" 24 veces sin añadir información.

**[OPINIÓN] Esto importa para el encargo.** Estos 13 informes se están usando como definición del estado del arte contra el cual medir el proyecto. **El contenido técnico es citable; la sección de conclusiones no lo es**, y conviene saberlo antes de tomar una decisión de arquitectura apoyándose en ella. Sumado a que el informe 06 está truncado en origen, **la recomendación es tratar el corpus como material de consulta con calidad desigual, no como especificación.** Extraje las ideas de los módulos 16-17 destilándolas; lo que sigue es mi lectura, no una cita.

## 9F.1 Las siete lecciones del informe, y qué hace TerraQuantum con cada una

| # | Lección del informe 04 | Estado en TQ | Veredicto |
|---|---|---|---|
| 1 | **Núcleo headless**: el motor geométrico/matemático jamás debe importar la capa de presentación (Qt, OpenGL, Vulkan). Comunicación por Observer/callbacks | Backend FastAPI sin GUI; frontend separado por HTTP | ✅ **Cumple, y con una frontera más dura que la del informe** (proceso separado, no solo módulo) |
| 2 | **Jamás reescribir BRep ni un motor de render desde cero**, salvo dominio verdaderamente único (Blender es la excepción justificada). Encapsular OCCT/VTK/CGAL tras APIs internas | `skimage.marching_cubes`, Three.js, scipy/numpy, pyproj | ✅ **Cumple.** Y §7.1 ya lo señaló como decisión excelente |
| 3 | **Serialización**: NO replicar un esquema binario propio (el `.blend`/SDNA de Blender es genial pero frágil de imitar). Usar **contenedor estándar** separando el árbol ligero de configuración (XML/JSON) de los binarios pesados | TQPKG (secciones `#CONFIG`/`#BOREHOLES`/`#PLAN` + CSV) + parquet/zarr aparte | ✅ **Cumple el principio.** *Matiz:* TQPKG es un formato de texto propio en vez de ZIP/HDF5; funciona, pero un ZIP con manifiesto JSON sería más estándar y más fácil de versionar |
| 4 | **DAG con nodos sucios**: recomputar solo las ramas afectadas, nunca recálculo global ciego | **No existe**: cada inversión recalcula todo desde cero | ❌ **Gap real**, y con destino claro: el bucle *perforar → anclar → re-invertir* de F11 es exactamente un problema de recómputo incremental. La semilla ya está construida (`/geophysics-live-update`, Woodbury) y sin cablear |
| 5 | **Struct-of-Arrays desde el inicio** (caché L1/L2 + transferencia a VRAM sin copias) | Arrays numpy + parquet columnar + Arrow IPC al visor | ✅ **Cumple** |
| 6 | **Exponer el 100% de la API a un lenguaje de scripting** para que terceros extiendan sin cargar al núcleo | El backend *es* Python, pero **no hay API de scripting para el usuario** ni sistema de plugins | ❌ **Gap.** Coincide con el 0% de "Automatización/scripting" del informe 03 (§4.7) |
| 7 | **Tests de regresión automatizados implacables**, críticos por la inestabilidad de las tolerancias epsilon; enganchados a CI/CD | Suite fuerte con oráculos reales… **que no corre en CI** (H-4) y con 66% de "gates" sin criterio automático (H-22) | ⚠️ **Construido y desconectado.** El informe considera esto *"la única forma comprobada de evolucionar un núcleo durante décadas sin perder la confianza acumulada"* |

## 9F.2 Los patrones recurrentes (módulo 16) frente a TQ

El informe identifica cinco patrones que comparten los proyectos que sobrevivieron su primera década:

1. **Model-View separado con Observer** → ✅ TQ lo cumple por arquitectura de proceso.
2. **Sistema de atributos tipo ECS-lite** (OCAF: etiquetas + atributos por GUID, huyendo de la herencia profunda) → ➖ No aplica: TQ no tiene un modelo de documento paramétrico con tipos heterogéneos.
3. **Command Pattern con deltas** para undo/redo — el informe insiste en guardar **incrementos**, nunca clonar el documento entero → ❌ **TQ no tiene undo** (§4.7). Y el informe aporta el diseño concreto que la Fase 13 debería seguir: deltas, no snapshots.
4. **Arquitectura de plugins** → ❌ No existe. **[OPINIÓN] Y aquí discrepo del informe para el caso de TQ:** el propósito de un sistema de plugins es escalar a cientos de colaboradores externos. Con un desarrollador y un nicho de consultores, construirlo hoy sería sobreingeniería pura. La API de scripting (lección 6) sí aporta valor inmediato; el sistema de plugins no.
5. **DAG de dependencias** → ❌ Ver lección 4.

## 9F.3 Lo que este informe cambia en la auditoría

**Nada de lo que ya estaba diagnosticado cambia de severidad**, pero aporta dos cosas:

- **Refuerza la Fase 13 (undo/redo)** con un diseño concreto: *Command Pattern con deltas*, explícitamente contra el patrón de clonar el estado completo — que es la implementación ingenua que un desarrollador solo tendería a escribir primero.
- **Añade un gap que no había registrado: la API de scripting.** El informe la llama *"una resolución de supervivencia, no una decisión cosmética"*, porque permite que terceros construyan lo vertical sin cargar al núcleo. Para TQ, cuyo usuario es un **consultor experto que repite el mismo flujo muchas veces al año**, exponer el pipeline como API Python invocable (procesar N surveys, re-generar reportes, automatizar el gabinete) es plausiblemente **más valioso que varias features de UI**. **[INFERENCIA]** Y el coste es bajo: el backend ya es Python y ya tiene los servicios factorizados; falta un punto de entrada documentado y estable, no código nuevo.

**[OPINIÓN] La conclusión estratégica del informe 04, destilada:** *"concentra tus recursos escasos en la lógica de tu dominio; delega todo lo demás a núcleos probados"*. TerraQuantum ya lo hace bien en geometría y render. **Lo hace mal en un solo sitio: mantiene 437 líneas de selectores de λ obsoletos y ~3.000 líneas de espina dorsal propia** (H-3, H-25) donde el valor diferencial no está. El valor está en la física validada y en la honestidad — no en la fontanería que la rodea.

---

# 9-SEPTIES. EL MOTOR MAGNÉTICO: DOS FUNCIONALES SEGÚN LA CONFIGURACIÓN (8ª pasada)

## 9G.1 [H-33] `depth_beta` actúa o no **según si el padding está activo** 🟠 ALTO

> ### ⚠️ TERCERA AUTOCORRECCIÓN DE ESTA AUDITORÍA
> En §9D.1 escribí que el motor magnético *"no tiene `Ws` y su depth-weighting **funciona**"*. **Es cierto solo en una de las dos rutas del solver.** Al leer el ensamblado completo descubrí que magnetometría tiene **dos funcionales de regularización distintos**, y cuál se usa depende de la configuración.

**[HECHO] El discriminador es si el bloque de smallness lleva el factor `Wz_inv`.**

**RUTA A — L2 sin anclajes ni padding** (`magnetometry.py:1470-1482`): la smallness es `λ·I` sobre `m̃` (vía `damp=λ` de LSQR, o `eye·λ` con bounds). El bloque **no** lleva `Wz_inv`. Como `m̃ = χ / w_z`, la penalización en espacio físico es `λ²·Σ(χⱼ /(zⱼ+z₀)^{β/2})²` → **las celdas profundas se penalizan menos → depth weighting ACTIVO.**

**RUTA B — con padding, o con anclajes, o con IRLS compacto** (`:1420`, `:1459`, `:1486`): la smallness es `diags(w) @ Wz_inv`. Y como el bloque de datos (`:1231`) y el de suavidad (`:1246`) **también** llevan `Wz_inv`, el sistema aumentado completo es `M @ Wz_inv`: un **cambio de variable puro**. La solución en espacio físico es independiente de `Wz_inv` → **depth weighting INERTE.**

**[MEDIDO] Verificación numérica** (script `verify_mag_two_paths.py`, solución comparada en susceptibilidad física):

| β | Ruta A — diferencia relativa vs β=1.5 | Ruta B — diferencia relativa |
|---|---:|---:|
| 0,0 | 2,8e+01 → **ACTÚA** | 1,4e−10 → **INERTE** |
| 0,5 | 9,8e+00 → ACTÚA | 1,5e−10 → INERTE |
| 1,0 | 2,4e+00 → ACTÚA | 1,3e−10 → INERTE |
| 3,0 | 9,8e−01 → ACTÚA | 2,9e−10 → INERTE |
| 6,0 | 1,0e+00 → ACTÚA | 8,7e−09 → INERTE |

En la ruta A cambiar β altera la solución en un 100–2.800%. En la ruta B no la altera en absoluto (ruido de punto flotante).

**[INFERENCIA] Cuál se usa en producción:** la ruta B. El padding es estándar en el motor (`padding_mask`, R-02, y el proyecto registra "padding magnético motor+prod" como corrección aplicada). **Es decir: en producción, el `depth_beta=1.5` de magnetometría tampoco actúa.**

### El cuadro completo, ya corregido

| Motor | Mecanismo | ¿`depth_beta` actúa? |
|---|---|---|
| Gravimetría | `W_z` **anulado** por la normalización de columnas `Ws` | ❌ Nunca (H-1) |
| Magnetometría, ruta A (sin padding) | smallness `λI` sobre `m̃`, sin factor `W_z` | ✅ Sí |
| **Magnetometría, ruta B (producción)** | todos los bloques comparten `W_z` → cambio de variable puro | ❌ No |

**Dos motores, tres comportamientos, un solo parámetro documentado como "depth weighting Li & Oldenburg".**

### Por qué esto es peor que un parámetro inerte

1. **La misma configuración nominal produce físicas distintas.** Activar el padding no solo añade celdas de amortiguación: **cambia el funcional de regularización**. Dos corridas con idéntico `depth_beta` y distinta configuración de padding no son comparables, y nada en la salida lo indica.
2. **Invalida parcialmente comparaciones históricas.** Cualquier experimento magnético que haya variado el padding entre brazos comparó dos regularizaciones distintas creyendo comparar una.
3. **El compromiso de "byte-idéntico al histórico" —que el proyecto prioriza con razón para no romper la física validada— aquí congeló una inconsistencia** en lugar de una decisión. El comentario de `:1471` dice literalmente *"byte-idéntico al histórico"*: preservó fielmente algo que nadie había comparado con la otra rama.

**Caveat honesto:** en la ruta B, `Wz_inv` sigue siendo un **precondicionador por la derecha** legítimo — cambia la trayectoria de LSQR. Con `atol=btol=1e-8` y 500 iteraciones, si el solver converge, el efecto sobre el resultado es nulo (lo medido); si trunca por iteraciones, habría un efecto residual de regularización implícita por parada temprana. No lo cuantifiqué.

**Recomendación.** Es el mismo arreglo que H-1 y refuerza la Fase 7: **una única función `build_model_weights()` compartida**, que decida explícitamente si el peso de profundidad entra en el funcional o no — y que lo declare en la salida de la corrida. Hoy esa decisión la toma, sin que nadie lo advierta, la presencia del padding.

## 9G.2 Lo demás de `magnetometry.py`

**[HECHO] Alcance de la lectura:** el solver principal (`solve_magnetic_inversion_lsqr`, 840 LOC) y el ensamblado. Los solvers MVI (`:2409`), amplitud (`:2684`) y tensor gradiente (`:2948`) quedaron sin leer en profundidad — siguen como pendiente.

- **Bien:** el kernel de prisma usa `r = np.sqrt(x²+y²+z²+eps)` (`:241`) con un epsilon de regularización, evitando la singularidad en la esquina del prisma. Correcto.
- **Riesgo menor [HECHO]:** `:693`, `inv_r2 = 1.0 / r2` en `build_gradient_tensor_kernels` sin guarda explícita. Si un sensor coincidiera exactamente con el centro de un vóxel daría división por cero. **[INFERENCIA]** Probablemente inalcanzable (los sensores están sobre la superficie y hay validación previa), pero es la única división sin protección que encontré en los dos motores, y el patrón defensivo del resto del código sugiere que es un olvido, no una decisión.
- **Confirmado:** la duplicación estructural con gravimetría (H-9) es real y ya está cuantificada; `_sigma_adaptive` (`:74`) es un port declarado.

---

# 9-OCTIES. UX COMPARADA Y ANTI-SCOPE ARGUMENTADO (9ª pasada)

*Cierra las dos últimas áreas pendientes: la UX contra el informe 03 (§4.7 era la sección más débil del informe) y el rechazo razonado de los informes 07 y 12. Verifiqué personalmente el hallazgo más citable; el resto lo relayo indicando su origen.*

## 9H.1 [H-34] El colormap arcoíris sigue vivo en la mitad del visor 🟡

**[MEDIDO — verificado por mí]** `lib/terraQuantumGeology.ts`:
- `:179` define `TURBO_STOPS` y `:569` lo aplica a la **susceptibilidad magnética** (`chiNorm`, escala logarítmica).
- `:195` define `DENSITY_VIRIDIS_STOPS` y `:613` lo aplica a la **densidad**.

**La migración a Viridis cubrió densidad y dejó magnetometría en Turbo.** El proyecto registra la migración como hecha (`4d72305`, "Viridis + piso-de-pico"); es cierto a medias.

**[OPINIÓN] Con un matiz de justicia técnica:** Turbo **no es Jet**. Google lo diseñó explícitamente para corregir los peores defectos de Jet y es notablemente mejor. Pero sigue siendo de la familia arcoíris: no es monótono en luminancia, introduce fronteras percibidas donde el dato es continuo y no sobrevive a la impresión en escala de grises ni al daltonismo — que es exactamente por lo que el informe 03 (Mód. 13) rechaza la familia entera.

**Por qué importa aquí más que en otro software:** el argumento de venta del producto es *"el 3D más claro y honesto de su rango de precio"*. Un mapa que fabrica fronteras visuales inexistentes es lo contrario de eso, y encima **rompe la coherencia interna**: el mismo visor comunica densidad con una escala perceptualmente uniforme y susceptibilidad con una que no lo es. Un consultor que compare ambas capas leerá estructura donde no la hay. **Coste de arreglo: sustituir una constante.**

## 9H.2 UX: el cuadro honesto contra el informe 03

*(Auditoría delegada; evidencia archivo:línea del agente, no re-verificada íntegra por mí salvo H-34.)*

**Lo que está bien, y merece decirse:**

| Módulo del informe 03 | Nivel | Evidencia |
|---|---:|---|
| **Flujos de larga duración** | **~90%** | `packageInversion.ts` (F3): cola + polling por etapas reales + cancelación + abandono seguro + presupuesto previo. **El informe trata esto como el requisito más duro para software científico, y TQ lo cumple bien** |
| **Workflows guiados** | ~90% | `PreparacionView` separa el flujo simple de un "Avanzado" colapsado con defaults sensatos — el patrón Leapfrog que su propia estrategia de mercado exige |
| **Gestión de estado** | ~85% | Store único con invalidación dirigida al cambiar la identidad de la corrida |
| **Errores accionables** | ~90% | Catálogo ES + `ErrorModal`, verificado en §9E.6 |

**Lo débil, con su coste real:**

| Gap | Nivel | Por qué importa (o no) |
|---|---:|---|
| **Colormap Turbo en magnetometría** | 55% | H-34. **Barato de arreglar, caro de no arreglar** en una demo. **SIGUE ABIERTO y sin fase dueña**: la Fase 13 lo dejó con nombre al cerrar, porque cambiar el colormap no es undo/redo |
| **Sin persistencia de sesión/layout** | 50% | La app fuerza una pantalla de bienvenida en cada recarga y no recuerda el estado. Para un experto que la abre a diario, es fricción diaria. **✅ Parcial en la Fase 13 (08-19)**: se persisten 12 preferencias de visualización, validadas clave a clave al rehidratar. **La bienvenida y la vista activa NO se restauran, por decisión escrita**; y queda declarado que el puerto variable de Tauri (3000..3011) puede vaciar el almacén en silencio |
| **Listener de teclado global sin aislamiento de foco** | — | Choca con los ~10 sliders del visor 3D: teclear en un control puede disparar atajos. **✅ CERRADO en la Fase 13**, y el diagnóstico se quedaba corto en dos cosas: son **8** sliders (no ~10 controles) porque las vistas son mutuamente excluyentes, y el `preventDefault()` incondicional no producía «doble efecto» sino **secuestro** — con un slider enfocado las flechas movían la cámara y el slider no se movía |
| **Sin invalidación "stale"** | — | Cambiar un parámetro sin re-invertir deja el resultado anterior en pantalla sin marcarlo como desactualizado. **Es la misma familia que H-28** (mostrar algo que ya no corresponde). **✅ CERRADO en la Fase 1** (`resultIsStale`) |
| **Undo/redo** | 0% | §4.7. El informe 04 aporta el diseño (deltas, no snapshots). **✅ CERRADO en la Fase 13 (08-19)**, y por deltas |
| **Automatización/scripting** | 0% | Fase 11. **✅ CERRADO (08-17)** |

**[OPINIÓN] Los 3 gaps que más costarían en una demo ante un consultor:** (1) el arcoíris magnético, porque un geofísico lo nota en segundos y desmiente el discurso de claridad; (2) el resultado obsoleto sin marcar, porque destruye confianza justo en el momento de decidir; (3) la falta de persistencia, porque en una demo se recarga la página y se pierde el contexto.

**Y los 3 que el informe pide pero que aquí serían sobreingeniería:** docking libre de paneles (el layout fijo de 3 zonas es **la decisión correcta** para un flujo lineal), un Tool Manager formal (TQ tiene una sola herramienta: invertir), y un sistema de plugins (§9F.2). Decirlo importa tanto como listar los gaps.

## 9H.3 Informes 07 y 12: rechazo argumentado

*(Delegado. El resultado es de calidad alta y lo suscribo; el argumento marco es mejor que el que yo había esbozado en §3.2.)*

**Informe 07 — Planificación minera.** El argumento decisivo no es "está fuera de scope", es de **clase matemática**:

> **TerraQuantum infiere un modelo de bloques (la incógnita). El informe 07 secuencia un modelo de bloques ya conocido (el dato).** Son problemas casi disjuntos pese a compartir vocabulario.

Todo lo demás cae por ahí: NSR, teoría de Lane, MILP de secuenciamiento, minería subterránea, geomecánica, tronadura y geometalurgia exigen **valorización económica por bloque** — precisamente el lenguaje (`reserve/resource/grade/NPV`) que el producto tiene **prohibido** en sus salidas por compliance JORC.

**Un punto se evaluó en serio y se rechazó por producto, no por dificultad:** usar max-flow/min-cut (Pseudoflow) para segmentar targets con fronteras nítidas. Técnicamente viable. **Pero contradice la filosofía B1/B2/B3**: dibujar un contorno nítido sobre un modelo no-único comunica una certeza que el dato no tiene. Es el diferenciador comercial lo que lo veta.

**Informe 12 — IA científica.** Dos rechazos con argumentos de distinta naturaleza, y ambos buenos:

- **CNN/U-Net para inversión gravimétrica directa (Mód. 7)** — el módulo técnicamente más relevante — se rechaza **por negocio**: entrenarlo exigiría *poolear gravimetrías de múltiples clientes*, lo que viola la promesa local-first sobre la que se sostiene la confianza del consultor. **No es backlog pendiente: es una vía que el producto no debe tomar nunca.** Conviene que esto quede escrito, porque es el tipo de "mejora obvia" que alguien propondrá dentro de un año.
- **PINN para inversión (Mód. 4)** se rechaza **por técnica**: el problema de TQ es **lineal**, con solución cerrada ya implementada (IRLS + Tikhonov + Morozov + LSMR) y dentro de presupuesto medido (30k vóxeles < 3 min). Una PINN sería estrictamente peor para el régimen de *una inversión por proyecto*: no amortiza el coste de entrenamiento.

**Hallazgo honesto sobre el informe 12:** **no discute LLMs conversacionales en ningún momento.** Por tanto **no refuta ni informa técnicamente la decisión F6** ("a Gemini no se le entrena"). Lo que sí hace su Mód. 15 es llegar, por el camino del ML geocientífico clásico, a la misma conclusión epistemológica: preferir métodos clásicos e interpretables cuando hay pocos datos y se exige auditabilidad. **Es corroboración filosófica externa, no evidencia técnica nueva** — y conviene no venderla como más de lo que es.

### Lo poco que rescataría (barra alta: ¿lo pagaría un consultor?)

1. **Vocabulario P10/P50/P90 y "dispersión de ensamble"** (Mód. 10 del informe 12) para comunicar la incertidumbre que TQ **ya calcula** (B1/B2/B3, shuttle de null-space). Esfuerzo bajo, cero cambios en el motor, y traduce el diferenciador al idioma que un consultor de recursos ya habla. **[OPINIÓN] Es el mejor retorno por esfuerzo de los tres.**
2. **El Mód. 15 como material de credibilidad**: que la literatura de ML recomiende métodos clásicos con datos escasos y exigencia de auditabilidad es un argumento de venta y contenido para el modo "Enseñar" del copiloto.
3. **Confirmación externa, sin trabajo:** la arquitectura por capas y el LOD por octree de TQ siguen el patrón estándar que describe el informe 07.

---

# 9-NONIES. INFORME 14 (NUEVO): ARQUITECTURA DE ESCALA INDUSTRIAL (10ª pasada)

*Informe añadido al corpus el 2026-08-04, después de iniciada esta auditoría. 8.438 palabras. **Es el más directamente aplicable de los 14 a la pregunta "¿está bien arquitecturado el sistema?"**, y por eso lo leí íntegro yo en vez de delegarlo. Calidad: los módulos 1–18 son sólidos y concretos; los 19–20 sufren la misma degradación verbosa del informe 04, aunque menos severa — el contenido es extraíble.*

## 9I.1 El modelo de capas del informe frente al de TerraQuantum

El informe prescribe cinco estratos con responsabilidades estrictas. Éste es el mapeo real:

| Estrato del informe 14 | Qué permite | Equivalente en TQ | Veredicto |
|---|---|---|---|
| **Core / Foundation** | Memoria, concurrencia, primitivas matemáticas, reflexión, serialización, carga de módulos, logging. **Nada de dominio ni UI** | `core/` (3.176 LOC) | ⚠️ **Violado en contenido** (§9I.2) |
| **Engines** | Motores técnicos ortogonales, sin lógica de negocio | `exploration/` (11.023 LOC) | ✅ Correcto |
| **Capabilities / Dominios** | Lógica del geólogo; orquesta motores | `services/` (26.362 LOC) | ✅ Correcto |
| **Framework / Integración** | Orquestadores de pipeline, task graph | `run_queue_service` + `geophysics_service` | ⚠️ Existe pero fundido con el dominio (H-3) |
| **Apps** | GUI, bindings Python, worker headless | `api/` + `terraquantum-web/` | ✅ Correcto (y el worker headless existe) |

**[MEDIDO] La dirección de las dependencias es limpia**, que es la parte difícil:

| Comprobación | Resultado |
|---|---|
| `core/` importa engines, services o api | **0** ✅ |
| `exploration/` (engines) importa services o api | **0** ✅ |
| `exploration/` importa `core/` (dirección permitida) | 8 ✅ |

**[OPINIÓN] Esto merece reconocimiento explícito.** El fallo más común en plataformas científicas que crecen sin arquitecto es la dependencia ascendente: el motor que acaba importando un servicio "solo para esta cosa". **TerraQuantum no tiene ni una sola.** Con 137.000 líneas y 25 fases de acreción, mantener la dirección de las flechas intacta es un resultado que muchos equipos con arquitecto dedicado no logran. La regla de oro del repo (backend y frontend en iteraciones separadas, cambios pequeños y aislados) parece haber protegido esto de forma indirecta.

## 9I.2 [H-35] El 41% del `Core` es dominio, no infraestructura 🟠

El informe es tajante sobre el principio de exclusión, y lo enuncia con ejemplos que dan casi risa de lo aplicables que son:

> *"El Core carece por completo de conocimiento sobre la existencia de mallas triangulares, **modelos de bloques mineros**, estratigrafía, ventanas emergentes, o formatos de archivo industriales."*

**[MEDIDO]** Contenido real de `core/` (3.176 LOC):

| Archivo | LOC | ¿Es infraestructura? |
|---|---:|---|
| `block_model_store.py` | **840** | ❌ **Dominio puro**: modelos de bloques — el ejemplo literal que el informe prohíbe |
| `errors.py` | 734 | ✅ Sí (catálogo de errores) |
| `geo_utils.py` | **412** | ❌ Dominio geoespacial |
| `license_service.py` | 306 | ✅ Sí (infraestructura de producto) |
| `config.py` | 183 | ✅ Sí |
| `storage.py` | 168 | ⚠️ Infraestructura, pero **muerta** (H-12) |
| `gee_client.py` | **54** | ❌ Integración con un servicio externo de dominio |
| resto | 479 | ✅ Sí (métricas, logging, auth, observabilidad) |

**1.306 de 3.176 líneas (41%) son dominio alojado en el Core.**

**Por qué importa, más allá de la pulcritud.** El Core es el estrato que el informe describe como *"el estrato geológico base que debe permanecer inalterado durante décadas"*. Su valor está en ser **microscópico y estable**. Cuando contiene un almacén de modelos de bloques de 840 líneas, cada cambio en el formato del block model toca el estrato que debería ser inmutable — y todo lo que depende de él queda expuesto a churn que no le corresponde. **[INFERENCIA]** Es también la razón por la que `core/block_model_store.py` aparece en el estudio de duplicación (§9B.1, 25 ventanas repetidas): la lógica de dominio en el Core no recibe la misma atención de diseño que la de `services/`.

**Arreglo:** mover `block_model_store` y `geo_utils` a `services/` (capa de dominio), y `gee_client` junto a `satellite_service`. **No hay dependencias ascendentes que romper** (§9I.1), así que es un movimiento de archivos con actualización de imports — de riesgo bajo. Va a la Fase 6. — **✅ HECHO el 2026-08-09**, con un matiz medido: *«no hay dependencias ascendentes que romper»* era cierto para las que existían, pero el movimiento **fabricaba** una (`core/utils.py` importaba `clean_trace_id` hacia arriba). Ver el registro de la Fase 6.

## 9I.3 Los tres antipatrones del informe: TQ tiene dos

El módulo 19 nombra tres patrones degenerativos. El diagnóstico es incómodamente preciso:

| Antipatrón | ¿Presente en TQ? | Evidencia |
|---|---|---|
| **God Objects** — superclases que aglutinan atributos cruzados, estado y referencias al renderizador | ✅ **Sí** | H-3: `run_geophysics_inversion` 1.996 LOC / CC=201; `solve_inversion_lsqr` 1.050 LOC / 39 args. Y H-16 en el frontend: `PrepPanel` con 41 `useState` |
| **Abstracción especulativa prematura** — fábricas polimórficas para "una docena de dispositivos exóticos" antes de que el flujo básico funcione | ✅ **Sí** | H-12: `core/storage.py`, jerarquía `StorageBackend` con backends S3 y GCS que lanzan `NotImplementedError`, **cero consumidores**, para una nube que el producto rechazó por estrategia |
| **Lógica numérica acoplada a la UI** | ❌ **No** | El backend no sabe que existe una interfaz. §9E.6 lo verificó: la frontera se respeta |

**[OPINIÓN] Dos de tres, y el que falta es el más difícil de arreglar a posteriori.** Que TerraQuantum haya evitado el acoplamiento numérico-UI —el antipatrón que el informe describe como el que "erradica instantáneamente la capacidad de ejecutar en HPC headless"— es la razón por la que las Fases 7 y 8 son *posibles*. Se puede partir un God Object; no se puede desacoplar retroactivamente un motor que llama a cuadros de diálogo.

## 9I.4 [H-36] El patrón que habría impedido H-28: datos evaluados de solo lectura 🟠

Éste es el hallazgo conceptual más valioso del informe nuevo, porque **conecta un patrón de arquitectura con un bug real ya diagnosticado**.

El informe describe el Depsgraph de Blender (módulo 1):

> *"Los datos persistentes (DNA) **nunca poseen campos de estado en tiempo de ejecución**. Cuando se modifica un parámetro, se hace una copia, se aplican los modificadores sobre la copia, y el resultado se almacena como datos **evaluados**. Los motores de render, exportación y físicas interactúan **exclusivamente con esa copia de solo lectura**, garantizando que los datos base permanezcan inmutables, consistentes y libres de corrupción."*

Y VTK aporta el mecanismo complementario: la marca de tiempo `MTime`. Una petición viaja aguas arriba por el grafo; **si un nodo descubre que está desactualizado respecto a su MTime, fuerza la reevaluación**.

**Ahora contrástese con los hallazgos de esta auditoría:**

| Hallazgo | Qué es | Qué patrón lo habría impedido |
|---|---|---|
| **H-28** | El modelo 3D del survey A sobrevive al cambiar al CSV B | **Datos evaluados con identidad**: el modelo evaluado pertenece a una corrida; si la fuente cambia, el evaluado es inválido **por construcción**, no por acordarse de limpiarlo |
| **Stale UX** (§9H.2) | Cambiar un parámetro deja el resultado anterior sin marcar | **MTime**: el nodo se marca sucio solo |
| **Lección 4 del informe 04** | No hay recómputo incremental | El mismo DAG con nodos sucios |

**[OPINIÓN] Los tres son el mismo agujero arquitectónico visto desde tres ángulos, y el informe 14 le pone nombre: no existe la noción de "dato evaluado" con procedencia y validez.** Hoy el modelo 3D es un objeto suelto en el store al que hay que acordarse de invalidar. Ésa es exactamente la disciplina que Blender eliminó hace quince años convirtiéndola en un invariante.

Esto **refuerza y reencuadra la Fase 1**: la corrección robusta que propuse allí (que el modelo lleve el identificador del paquete que lo originó y la vista se niegue a pintarlo si no coincide) **no es un parche defensivo: es la versión mínima del patrón que la industria considera canónico**. Y abre el camino natural hacia el recómputo incremental de F11 sin rediseñar nada después.

## 9I.5 Lo que el informe valida sin reservas

- **Monorepo.** El informe lo defiende explícitamente frente al multi-repo para software científico, por la atomicidad de las refactorizaciones cruzadas. TQ ya lo es. ✅
- **Monolito modular sobre microservicios.** El informe es contundente: dividir en microservicios web cuando se intercambian bloques geométricos de GB es *"un suicidio de latencias e I/O"*. TQ es un monolito modular local. ✅ **Y esto valida retroactivamente la eliminación de Celery/Redis en F3** — que el proyecto justificó por local-first, y que el informe justifica además por arquitectura.
- **Núcleo headless.** ✅ Cumplido, y con frontera de proceso.
- **Solvers desacoplados del pre/post-proceso, comunicados por formatos jerárquicos.** TQ usa parquet/zarr donde el informe dice HDF5/CGNS: equivalente moderno y, para su escala, mejor elección. ✅

## 9I.6 Lo que NO tomaría de este informe

**[OPINIÓN]** Con la misma franqueza: el informe está escrito para plataformas de millones de líneas y equipos de decenas de personas, y varias de sus prescripciones serían dañinas aquí.

| Prescripción | Por qué no |
|---|---|
| **ABI estable, Pimpl, contratos C++ virtuales** | No aplica: Python no tiene ese problema. Adoptar el patrón mental sería fricción pura |
| **Sistema de plugins con sandbox y carga dinámica** | Mismo argumento que en §9F.2: sirve para escalar a cientos de colaboradores externos. Aquí hay uno |
| **Bazel/CMake con reglas de visibilidad por contrato** | Un `pyproject` y una prueba de capas (que se puede escribir en 30 líneas con AST, como hice en §9I.1) dan el 90% del valor al 2% del coste |
| **Reflexión, recolector determinista, task graph propio** | Infraestructura de motor nativo. En Python es reinventar lo que ya existe |
| **Separar `/engines` en librerías compiladas independientes** | El beneficio (compilación separada, ABI) no existe en Python; el coste (fricción de imports) sí |

**La lección que sí vale y es barata:** el informe insiste en que **el build debe imponer las reglas de visibilidad, no la disciplina humana**. En TQ eso se traduce en algo concreto y de coste casi nulo: **un test de capas que falle si `core/` importa hacia arriba o si aparece dominio nuevo en el Core.** Hoy la dirección es limpia por disciplina; un test la haría limpia por construcción. Va a la Fase 3.

---

# 9-DECIES. LOS SOLVERS MAGNÉTICOS SECUNDARIOS (11ª pasada) — el último hueco

*Cierra el único hueco de sustancia que quedaba: MVI, amplitud y tensor gradiente (~800 LOC). **Resultó ser la pasada más productiva de las once.***

## 9J.1 [H-37] Un modo de inversión que la UI ofrece y el motor nunca ejecuta 🔴 CRÍTICO

**[MEDIDO — verificado por mí, los cinco eslabones]**

| # | Eslabón | Evidencia |
|---|---|---|
| 1 | El esquema declara el modo | `schemas/geophysics_schema.py:134` — `inversion_mode: Literal["induced_only","total_field","amplitude"]`, con descripción *"'amplitude': inversión de amplitud \|J_total\| dirección-independiente"* |
| 2 | El frontend lo ofrece en un `<select>` real | `MagneticRemanenceForm.tsx:30` etiqueta *"Amplitud \|J_total\| — dir.-independiente"*; `:76-77` es el control |
| 3 | El componente **está montado** | `PrepPanel.tsx:13` lo importa y `:1885` lo renderiza |
| 4 | El valor viaja al backend | `PrepPanel.tsx:982` lo escribe en la configuración del paquete |
| 5 | **El backend lo acepta y nunca lo despacha** | `geophysics_service.py:2029` incluye `"amplitude"` en `_use_remanence`… pero `:2035` es `if _use_remanence and _rem.inversion_mode == "total_field"`. **No existe ningún `elif` para `amplitude`** |

Y el remate: **[MEDIDO]** `solve_amplitude_inversion_lsqr` aparece en todo el repositorio únicamente en su propia definición (`magnetometry.py:2684`) y en `tests/test_fase1_amplitude_inversion.py`. **Cero llamadores de producción.**

**Qué ocurre en la práctica.** El usuario abre Preparación, despliega el formulario de remanencia, elige *"Amplitud"* esperando robustez frente a remanencia oblicua —el caso documentado: IOCG y magnetita chilena con rotación tectónica de la Falla de Atacama—, y el motor ejecuta **la inversión TMI inducida estándar**: exactamente la que el modo amplitud existe para superar. Después, `geophysics_service.py:2199` escribe en el reporte `"inversion_mode": "amplitude"`.

**[OPINIÓN] Esto es corrupción silenciosa de la familia exacta que el proyecto declara como enemigo número uno**, y en su forma más peligrosa: no es un dato de entrada mal parseado, es **el reporte afirmando qué física se ejecutó, y afirmándolo mal**. Los dos bugs históricos que el proyecto cazó y celebra (decimal-coma, doble-Bouguer) corrompían números; éste corrompe **la procedencia del resultado**, que es el sustento del reporte honesto B1/B2/B3 y del escudo legal ante un QP que firma.

Es además **alcanzable en dos clics** desde la interfaz, a diferencia de la física muerta de H-31.

**Matiz justo:** el modo por defecto es `induced_only` (`MagneticRemanenceForm.tsx:40`) y `total_field` **sí funciona** (su rama existe). El defecto es específico de `amplitude`.

**Arreglo, por orden de honestidad:** (a) **inmediato y correcto** — rechazar `amplitude` con un error del catálogo ES ("modo no disponible en esta versión") y retirarlo del `<select>`; (b) **completo** — cablear `solve_amplitude_inversion_lsqr`, que ya existe y tiene tests. Lo que **no** es aceptable es dejarlo aceptando y mintiendo. Va a la Fase 1 con prioridad P0.

## 9J.2 [H-38] El padding es incondicional en producción: `depth_beta` es inerte también en MVI 🟠

Esta pasada **cierra la inferencia que dejé abierta en §9G.1**.

**[HECHO]** La cadena de pesos de `solve_mvi_inversion_lsqr` (`magnetometry.py:2519-2598`) es la misma que la del solver escalar: `Wd` → `Wz_inv` sobre los tres bloques de datos (`:2536-2538`), `L_scaled = L_active @ Wz_inv` (`:2546-2552`). Y la smallness:
- **sin padding** (`:2597`): `lsqr(..., damp=lambda_mag)` sobre `m̃` → **`depth_beta` actúa**;
- **con padding** (`:2590-2591`): `_small_blk = diags(ws3) @ Wz_inv3` → todos los bloques comparten `Wz_inv` como factor derecho → **se cancela**.

**El dato nuevo y decisivo [HECHO]:** `geophysics_service.py:1899-1916` construye `build_tensor_mesh_with_padding(params)` **incondicionalmente para toda inversión magnética** —sin flag opt-in, con el comentario explícito "paridad con gravedad"— y `_padding_mask_mag = ~is_core` se pasa siempre al solver (`:2092`).

**Conclusión:** en producción el padding **nunca** es `None`. Por tanto:
- Se confirma como **[MEDIDO]**, no como inferencia, que la ruta B es la de producción (§9G.1).
- **`depth_beta` es inerte en producción en los tres solvers**: gravimetría (anulado por `Ws`), magnético escalar y MVI (cancelado por factor común).

**[OPINIÓN] Y esto cambia el diagnóstico de fondo.** Con una sola instancia, `depth_beta` inerte parecía un bug puntual. Con tres instancias independientes, en dos motores y tres solvers, **es una propiedad del diseño del bloque de padding**: cada vez que alguien añadió una smallness diferencial (para padding, anclas o IRLS), la envolvió en `Wz_inv` por simetría con los demás bloques — que es lo natural y lo que rompe el peso de profundidad. No fue descuido: fue coherencia local aplicada sin una vista global del funcional. Refuerza la Fase 7: la solución no es parchear tres sitios, es **tener un único sitio**.

MVI está **100% cableado a producción** (dispatch en `:2081` cuando `magnetization_model='vector'`, con test E2E en `test_fase20c_mvi.py`), así que `depth_beta` es visible en la API y en `solver_meta` sugiriendo un control sobre la profundidad que no existe.

## 9J.3 [H-39] Los kernels de MVI y tensor ignoran `near_field_mode='prism'` 🟠

**[HECHO]** `build_mvi_kernels` (`:521-629`) y `build_gradient_tensor_kernels` (`:631-730`) **nunca leen `self.near_field_mode`**: usan siempre la fórmula dipolar. La rama de prisma sí existe, pero solo en `_build_sparse_kernel` (`:312-396`).

El esquema expone `magnetic_near_field: Literal["dipole","prism"]` (`geophysics_schema.py:597-603`) con la descripción *"Recomendado para targeting de cuerpos magnéticos someros (kimberlitas, IOCG aflorante)"*, y `geophysics_service.py:1958` construye el `forward` con ese valor — **el mismo objeto que se pasa a MVI**, que lo ignora.

**La ironía:** el docstring de MVI (`:2443`) dice que existe para *"IOCG/magnetita chilena con rotación tectónica"* — cuerpos someros con remanencia, **exactamente el régimen donde el esquema recomienda prisma**. Quien active `prism` esperando esa corrección la obtiene en el modo escalar y no en MVI, sin aviso.

**Atenuante [MEDIDO]:** `magnetic_near_field` no está expuesto en el frontend, así que hoy solo afecta a consumidores directos de la API o scripts. Es la misma familia que H-37 (una opción que no hace lo que dice) pero con alcance mucho menor.

## 9J.4 El tensor gradiente: cómo se hace bien

Justo es decirlo, porque contrasta con todo lo anterior. `solve_gradient_tensor_inversion_lsqr` (`:2948`, ~80 LOC) es **el diseño correcto**:

- **Cero duplicación:** delega el 100% en el solver principal vía `override_kernel`. Frente a los 840 LOC del escalar y 274 del MVI, resolver el problema en 80 líneas reutilizando el motor es la decisión que las Fases 7 y 8 persiguen. **Ya existe el ejemplo dentro del propio archivo.**
- **Honestidad documentada:** su docstring advierte que el depth-weighting β=1.5, calibrado para el decaimiento 1/r³, **no transfiere** al 1/r⁴ del tensor. Es exactamente la clase de caveat que el resto del motor debería llevar.

**Defecto menor [HECHO]:** hardcodea `topography_elevations=None`, así que nunca respeta topografía real — y colisionaría con `TypeError` si un llamador intentara pasarla. Dado que también carece de llamadores de producción, es de bajo impacto hoy.

## 9J.5 Otros hallazgos de la pasada

- **[HECHO] MVI no tiene bounds físicos de ningún tipo** —ni parámetro ni clip post-solve—, a diferencia del solver escalar (`susc_min/max`) y del de amplitud. Nada impide una susceptibilidad negativa o físicamente imposible en el modelo vectorial.
- **[MEDIDO] `solve_amplitude_inversion_lsqr` y `solve_gradient_tensor_inversion_lsqr` no tienen llamadores de producción.** Son ~343 LOC de física implementada y probada que no llega al usuario — con la diferencia crítica de que **amplitud sí está anunciada en la UI** (H-37) y tensor no.

---

# 10. PLAN MAESTRO DE EVOLUCIÓN

Ordenado por **valor estratégico**, no por facilidad. Esfuerzo en S/M/L/XL.

> **Renumeración (revisión posterior a la auditoría).** En la primera entrega las fases se rotularon **A…M en el orden en que se fueron derivando** durante las 11 pasadas, y una tabla aparte fijaba el orden de ejecución. Eso obligaba a leer dos sitios y se prestaba a ejecutar el plan en el orden equivocado. **Ahora el número de fase ES el orden de ejecución**: la Fase 1 va primero y así hacia abajo. Cada fase conserva su letra original como alias para que las referencias externas sigan siendo rastreables.

| # | Fase | Qué resuelve | Esfuerzo | Prior. | Hallazgos |
|---:|---|---|---|---|---|
| **1** | **Los bugs de confianza del camino dorado** *(antes L)* | **Muestra resultados que no son de tus datos, y un modo que miente** | S | 🔴 **P0** | H-27, H-28, H-29, **H-37**, H-34 |
| **2** | **Que el instalador falle en voz alta** *(antes K)* | **El producto no arranca y no lo dice** | M | 🔴 **P0** | H-17…H-21, H-23 |
| **3** | **Red de seguridad real** *(antes C)* | La CI no defiende lo que la doc promete | S | 🟠 P1 | H-4, H-5, H-22 |
| **4** | **Resolver el depth-weighting inerte** *(antes A)* | No se sabe qué producto se tiene | S | 🔴 **P0** | H-1 |
| 5 | **Cerrar la superficie de configuración** *(antes I)* | 29/44 flags sin ejercitar | S | 🟡 P2 | H-11, H-15 |
| 6 | **Limpieza verificada** *(antes D)* | Código muerto, deps, clave privada | S | 🟡 P2 | H-2, H-6, H-7, H-12, H-13, H-14 |
| 7 | **Extraer el motor común** *(antes B-0)* | Prerrequisito para cablear la Fase 4 | M | 🟠 P1 | H-9, H-33 |
| 8 | **Partir la espina dorsal** *(antes B)* | Coste marginal creciente por feature | L | 🟠 P1 | H-3 |
| **9** ∥ | **Interfaz de F7 y gates con criterio de usuario** *(antes H)* | **Bloquea la monetización** | M | 🟠 P1 | H-10 |
| 10 ∥ | **Contratos tipados + `PrepPanel`** *(antes J)* | Divergencia silenciosa de contratos; el estado que causa H-28/H-29 | M | 🟠 P1 | H-16, H-30 |
| 11 | **API de scripting** *(antes M)* | El usuario experto no puede automatizar | S/M | 🟠 P1 | §9F.3 |
| 12 ∥ | **OMF** *(antes E)* | Interoperabilidad comercial | M | 🟡 P2 | §4.2 |
| 13 | **Undo/redo y UX experta** *(antes F)* | Gap frente a Leapfrog; se encarece con el tiempo | L | 🟡 P2 | §4.7 |
| 14 | **Cablear RBF/HRBF** *(antes G)* | Pieza construida sin cablear de mayor valor | M | 🟢 P3 | §4.4 |

**∥ = paralelizable** con lo anterior: son frontend o backend aislado y no tocan el motor, así que su posición en la lista marca prioridad, no bloqueo.

**Estado de ejecución.** ✅ **Fase 1** (2026-08-08) · ✅ **Fase 2** (2026-08-10) · ✅ **Fase 3** (2026-08-12, **cerrada del todo el 2026-08-13**: la CI estaba en rojo por dos causas medidas y el criterio «CI roja si la física regresiona» no se cumplía) · ✅ **Fase 4** (2026-08-14, **cerrada CERRANDO**: 3.450 inversiones dicen que ningún β fijo mejora la profundidad en todos los regímenes; el límite es el null-space, no un bug — y de paso aparecieron **dos** funcionales de regularización en gravimetría, no uno) · ✅ **Fase 6** (2026-08-09, **cerrada del todo el 2026-08-14**: H-13 pedía revisar 16 símbolos «uno a uno» y la primera pasada resolvió los 6 que §9B.5 había listado por nombre — al volver a MEDIR aparecieron 11 más, ninguno en la tabla original, incluido un Gauge de Prometheus que publicaba «0 inversiones activas» mientras había una corriendo). **Dejó dos deberes medidos a la Fase 4**: `test_fase7_wiring::test_e2e_enabled_changes_model_and_reports` falla por un 9% bajo su umbral **igual con y sin el cierre** (A/B), y `test_fase4_depth_weighting::test_effective_model_weight_...` **pasa aislado y falla en la suite** — depende del orden, así que hoy no defiende nada. · ✅ **Fase 5** (2026-08-15: las 44 variables medidas por AST son **42** de superficie real; la sonda de la Fase 3 comprobaba que el módulo *carga*, no que la variable *llegue*; y aparecieron **cinco huecos que la auditoría no había visto** — una perilla inerte, un rollback que no rollbackeaba con `0`, un flag de seguridad que se encendía estando **vacío**, un reporte que afirmaba un solver que no corrió, y tres números que morían sin decir su nombre). · ✅ **Fase 7** (2026-08-15: **192 → 20** ventanas duplicadas con byte-identidad en **34/34** casos; y tres cosas que no estaban en el guion — el `study_duplication.py` que el criterio (a) citaba **no existía** en el repositorio y hubo que reconstruirlo; el escáner de λ medía con un operador que la Fase 4 había retirado, con un ratio de χ² de **23× a 12.700×** creciente con la profundidad y **0/4** aciertos en la elección de λ, hoy **4/4** y ratio **1,0000** con el box abierto; y el caveat que H-33 dejó sin cuantificar vale **66 %–86 %**, no un redondeo: la solución exacta de la ruta B es invariante a 1e-11 pero el LSQR termina por límite de iteraciones —`istop=7`, 500/500— y el motor **descartaba ese criterio de parada**). Cada una lleva su registro `### ✅ EJECUTADA` al final de su sección, con lo que se midió y lo que se dejó fuera a propósito. · ✅ **Fase 8** (2026-08-16: la espina partida y **medida** — `run_geophysics_inversion` 2.030 → **152** líneas y CC 183 → **12**; `invert_gravity_csv` 927 → **54** con 41 → **9** parámetros; `solve_inversion_lsqr` 1.046 → **212** y CC 124 → **12**; todo con byte-identidad verificada —28 casos de servicio y API, 34 de motor— y **sin reescribir una línea**: los cuerpos se movieron textualmente y las fronteras se calcularon con AST. Tres cosas fuera del guion: **Morozov re-liga λ** y partir la función lo rompía en silencio; agrupar los 41 parámetros como dice el plano —`Annotated[Modelo, Form()]`— **cambia el contrato HTTP** y hubo que hacerlo con `Depends`; y la configuración **no puede** subir a nivel de módulo porque cinco sondas la fijan por atributo. El deber de `iter_lim=500` queda **decidido: no se sube** — en gravimetría el límite no ata (Δ = 0,000e+00 exacto) y en magnetometría subirlo no mejora el χ² —ya está en 1e-14— sino que mueve el modelo hasta un **66 %** por el espacio nulo).

· ✅ **Fase 9** (2026-08-16: H-10 cerrado — la superficie F7 entera pasa de **5 endpoints sin un solo consumidor** a tener camino de usuario, y los 3 paneles que la Fase 6 encontró escritos-y-sin-montar quedan montados: **componentes `.tsx` sin importador, 3 → 0**. Lo que no estaba en el plan y salió al medir: **cinco defectos de honestidad**, todos en el lado que la fase venía a hacer visible — `copilot_gemini.configured` era `False` **constante** porque leía un atributo inexistente tras un `hasattr`; `/system/connectivity` devolvía `probed: true` **sin haber tocado la red jamás**; el copiloto pintaba un «Online» **literal en el JSX**; el widget del solver afirmaba «≤150 iteraciones» justo cuando **no tenía el dato**, tapando el `500/500` que es la evidencia de no-convergencia; y `MultimodalComboPanel`, nunca ejecutado por nunca haber sido importado, **tumbaba la pestaña entera** ante un plan incompleto. El cambio de proceso se implementó **midiendo**: `test_fase9_camino_de_usuario.py` recorre los tres eslabones —endpoint → proxy/cliente → componente montado— con excepciones que llevan motivo y fase dueña, y verificado por mutación que la allowlist es portante. Y la **auditoría retroactiva de F5–F8 dio 4 de 4**: cada una de esas fases entregó algo que el usuario no podía ver — el caso más llamativo, los 6 campos de solver de la Fase 5, incluido su arreglo estrella de distinguir el solver *pedido* del *usado*, que aparecían en **0 archivos** del frontend).

· ✅ **Fase 10** (2026-08-17: H-16 cerrado — el contrato del camino dorado deja de escribirse a mano. **Medido antes de ejecutar, y la justificación de la fase estaba mal contada:** H-16 decía «40 nombres de tipo duplicados» y son **13**; `SniffReport ×3` y `BuildPackageConfig ×3` eran falsos —están declarados UNA vez y re-importados—, porque el contador tomaba las líneas `type X,` de un bloque `import` por declaraciones. **El problema real era otro y mayor:** de 65 rutas, **44 no declaraban esquema de respuesta**, incluida la cadena de ingesta completa, así que el OpenAPI del camino dorado iba vacío y no había *nada* que generar. Dos riesgos medidos al declararlo, y muerden en direcciones opuestas: un `response_model` **estricto borra en silencio** los campos que no declara, y uno **a secas inyecta** los opcionales que el endpoint no emitió —apareció `user_supplied_key: null` en 3 de las 4 features de conectividad—; la contra es `response_model_exclude_unset=True`, y hay test que compara la respuesta HTTP con la del servicio, clave a clave. **Tres hallazgos nuevos:** `POST /license/activate` **nunca devuelve `mode`** y `/license/status` sí, mientras el frontend usaba UN tipo con `mode` obligatorio para las dos; **en un contrato de respuesta un default es una promesa que nadie quiso hacer** (`default_factory` marcaba opcionales 25 campos que el servicio emite siempre, y el frontend se llenaba de guardas para casos imposibles); y `inclinationDeg`/`declinationDeg`/`fieldIntensityNt`/`suscMin`/`suscMax` **no tienen ningún setter**: el comentario prometía que el usuario podía ajustarlos y no hay un solo input — `useState` lo escondía y el paso a `useReducer` lo delató. Estado: **41 → 0 `useState`** en `PrepPanel`, y el máximo del frontend entero pasa de **41 a 9**. Gate: 15/15 del guard nuevo, tsc 0, eslint 0, **28/28 Playwright**, 6 mutaciones verificadas.)

· ✅ **Fase 11** (2026-08-17: la API de scripting existe y el camino dorado deja de exigir una interfaz. **La decisión de diseño se tomó midiendo**: la API llama a los ENDPOINTS y monta la app en el propio proceso —sin servidor, sin puerto, sin red— porque el camino dorado **no vive entero en `services/`**: `load-package` tiene ~250 líneas de orquestación en el handler HTTP (grilla efectiva, ruteo magnético, σ por estación, topografía condicional, sondajes persistidos, presupuesto de vóxeles), y reconstruir eso desde los servicios habría sido una segunda implementación del camino dorado — H-29 otra vez. Hay un test que compara el payload de la API con el del endpoint llamado a mano, byte a byte, **con un control que demuestra que la comparación sabe distinguirlos**. **El hallazgo de la fase**: por el camino natural, «procesa estos 12 surveys» —la frase con la que el informe la justifica— **falla en el survey 11** con `429` (10/minuto en `enrich-package` y `load-package`) y la respuesta **no trae `Retry-After`**, así que ningún cliente puede saber cuánto esperar; `Session` lo resuelve con política explícita (`reset` en proceso, donde el limitador no protege ningún perímetro porque el «cliente remoto» ES el script; `wait` remoto con backoff declarado ciego; `raise` para medirlo). **Y tres defectos del backend que destapó la propia API el primer día**, ninguno arreglado allí a propósito y los tres pinchados por tests de caracterización que se pondrán rojos el día que alguien los arregle: **H-F11-1** (🔴) un CSV `X,Y,Z` —el encabezado de los DOS benchmarks magnéticos publicados— automapea el **northing al rol PROFUNDIDAD**, y la guarda que existe para esto (`northing_in_depth_slot`) exige `>1e5 m`, así que caza a DO-27 (7,1e6) y **no a Raglan** (4,1e4, coordenadas locales), que pasa con `needs_mapping=False`, `needs_confirmation=False` y `suspicions=[]` para morir después con «el kernel magnético G_active quedó vacío», que apunta al sitio equivocado; **H-F11-2** (🟠) el auto-grid propone `nx=82`/`nz=81` y el esquema exige `≤80` → error CRUDO de Pydantic con URL de `errors.pydantic.dev`, y la asimetría está a la vista en `_eff_dim`, que acota el valor del USUARIO y devuelve el AUTOMÁTICO sin acotar; **H-F11-3** (🟠) la rama **síncrona** —la que el endpoint recomienda para scripts— no llama a `project_store.record_run`, así que **doce surveys procesados desde un script no aparecen en la pantalla «Historial»** (con `wait=False` sí: medido en los dos sentidos). Criterio de aceptación cumplido: `examples/01` reproduce el camino dorado completo sobre **Laguna del Maule desde el CSV crudo de un Excel chileno** (preámbulo, `;`, coma decimal, cabeceras en español) en ~20 líneas; versión declarada **v0** y promesa de estabilidad escrita en `docs/08_API_SCRIPTING.md`, con lo que haría falta para llamarla v1. De los 4 datasets canónicos, **3 completan la ruta del usuario** y San Nicolás queda declarado **no evaluable** —su dato es un `.mat` sin versionar y no hay conversor— con la disciplina de `DatosNoVersionados`. **La deuda heredada se cierra midiendo:** los 17 contratos con `?` no eran opcionalidad sino **serialización** —si la ruta no usa `exclude_unset`, FastAPI serializa el modelo entero y el campo viaja siempre—, así que `json_schema_serialization_defaults_required` lo declara **sin quitar un solo default** (cero riesgo de 500, que fue lo que hizo revertir el intento de la Fase 10): **78 campos pierden el `?`**, `CONTRATOS_AUN_A_MANO` baja de **19 a 4** y ninguna de las 4 es «todavía no lo hice». También se mide lo que la Fase 10 dejó como no-medible: la inyección de `/preview` son **2 claves** y la de `/invert` **4**, todas gemelas snake_case de campos camelCase reales. Gate: **31/31** de la suite nueva · **7 de 7 mutaciones cazadas** · tsc **43 → 0** · `next build` OK · guards de las Fases 3, 9 y 10 en verde.)

· ✅ **Fase 12** (2026-08-18: OMF de ida y vuelta, con la dependencia `omf==1.0.1` **autorizada expresamente**. La elección de librería se midió en vez de leerse: el fork vivo `mira-omf` está mejor mantenido pero arrastra `geoh5py` **LGPL**, inadmisible sin decisión explícita en un producto que se firma y se vende, y `omf` 1.0.1 —MIT, abandonada en 2019— se comprobó **antes de instalarla** cargándola desde `sys.path`: hace round-trip completo en Python 3.14.4 con numpy 2.4.4. **El hallazgo de la fase es que exportar a OMF obliga a mirar los ejes**, y ahí el bundle industrial estaba mal: el modelo interno es (Este, PROFUNDIDAD↓, Norte) y la permutación correcta existe en `gravity_import_service`, pero el ZIP no la aplica — sobre una corrida real, el `model.msh` **en disco** dice `20 20 10` y el del ZIP dice `20 10 20`, mismo nombre y misma corrida con **Norte y profundidad intercambiados** (**H-F12-1**, pinchado y no arreglado: tocar el bundle no era el alcance). Otros dos, ajenos: **`omfvista` lee las celdas transpuestas** respecto de la especificación de GMG —se escribe según la ESPECIFICACIÓN y queda test para que nadie «corrija» el exportador— y **`omf.OMFReader` no cierra el fichero**, lo que en Windows convertía un 422 limpio en un 500. Nada se inventa, y se midió: georreferenciar exige origen absoluto **y** CRS proyectado, que cumplen **25 de 105** proyectos; sin datum vertical en todo el repo, Z se declara profundidad y no cota; la corrida conjunta se rechaza con 422 en vez de inferirle una malla; y los atributos se curan midiendo —`grade` es NaN en el 100 % de las celdas y `rho`/`density`/`density_t_m3` son el mismo array bit a bit—. El guard de la Fase 9 cazó el endpoint de importación sin consumidor y se **cableó**, no se toleró. Gate: 16/16 · tsc 0 · eslint 0 · `next build` OK. **Criterio de aceptación parcialmente cumplido y así se declara**: no se ha abierto el fichero en un visor de terceros.)

· ✅ **Fase 13** (2026-08-19: undo/redo por deltas, atajos con foco y persistencia de preferencias. **Medir antes de ejecutar cambió la fase.** El plan decía «middleware de Zustand que registre comandos inversibles para las acciones del usuario»; al medir el store salió que de sus **93 acciones, 44 no tienen ni un llamador** en todo el árbol, y —lo grave— que **`Scene3D` SÍ lee** `showVoxels`, `visualLayer`, `voxelOpacity`, `voxelScale`, `minTargetScore`, `showFloor`, `showTerrain`, `sliceThickness`, `doiThreshold` y otras: son **perillas que el visor honra y que ningún control montado puede mover**. Es la familia H-10/H-37 otra vez, y un undo sobre ellas habría sido teatro. Deshacible es lo que **un control montado cambia**: 16 claves de 100. **El cierre del patrón de §1.2 es por TIPOS, no por disciplina**: `NO_DESHACIBLE` se declara como `Record<Exclude<CampoDeEstado, ClaveDeshacible>, string>`, el complemento EXACTO — añadir un campo al store y no clasificarlo **no compila** (verificado por mutación: quitar `gestureMode` da `TS2741`). **Deltas y no instantáneas**, como pide el informe 04 (§9F.2), con el argumento cuantitativo medido aquí: `GravityCorrectionWizard` guarda el CSV parseado entero y el modelo llega a ~1,7 M de vóxeles; el guard prohíbe el clonado total en los módulos del historial, con test de control que demuestra que el detector discrimina. **El criterio «no interfiere con corridas en curso» se cumple en dos capas**: por construcción (`activeRun`, `model`, `view`, `show3D` y todos los payloads son indeshacibles: un Ctrl+Z no tiene por dónde tocar una corrida) y por una puerta que además evita el desperdicio — y le da a `isBlockModelLoading` **su primer lector** en todo el repositorio. **El hueco se declara**: entre el clic de «Cargar modelo 3D» y la primera escritura de identidad el paquete se está SUBIENDO y el store no dice nada (`LoadPanel` lleva su `loading` en estado local); es benigno porque todavía no hay modelo, y cerrarlo exigiría tocar el camino dorado. **Tres hallazgos nuevos, ninguno en el plan.** (1) 🟠 El listener de flechas de `Scene3D` no era «doble efecto» como decía §9H.2: llamaba a `preventDefault()` **incondicionalmente** desde `window` en fase de burbuja, así que **secuestraba** las flechas y dejaba los **8 sliders** del visor inoperables por teclado (6 del corte caja, 1 de sección, 1 del umbral conjunto). Y el número de la auditoría estaba mal: no son ~10 controles sueltos, y los 21 inputs de `PrepPanel` **nunca coexisten** con ese listener porque las vistas son mutuamente excluyentes. *[El «el slider no se mueve» es DEDUCIDO del código y de la especificación HTML, no verificado en navegador; lo MEDIDO es que no había filtro de foco y que el `preventDefault` era incondicional.]* (2) 🟠 `showBoreholes` y `showDoiOverlay` **sólo cargaban sus datos dentro del manejador del clic**: cualquier otro camino que los encendiera dejaba la capa en «ON» y vacía, sin error visible — y en el horizonte DOI eso es afirmar una profundidad de investigación que nadie calculó. Reparado: los datos siguen al estado. (3) 🟢 `lucide-react` está declarada en `package.json` y **no la importa ni un fichero**; no se estrenó por dos flechas. **La barrera es una regla de seguridad de datos, no una comodidad**: cambiar de archivo BORRA el historial de preparación, porque H-29 fue exactamente un reconocimiento de riesgo marcado sobre el archivo A que viajaba describiendo el archivo B, y un Ctrl+Z que cruzara ese límite lo resucitaría. Por eso los dos reconocimientos quedan además **fuera** del historial: un atajo de teclado no es una lectura del riesgo. Y por eso no hizo falta inventar comandos transaccionales: la única acción que cruza las cuatro máquinas de la Fase 10 es justamente el cambio de archivo. `prepPanelState.ts` queda con **0 líneas modificadas** (el envoltorio intercepta su acción de restaurar antes de delegar, así que la comprobación `never` de los cuatro reducers sigue viva). **Persistencia con su caveat medido y escrito**: sólo preferencias (12 claves), nunca datos de una corrida; lo que va en coordenadas del modelo (`slicePosition`, `clipBox`) se excluye con motivo; el almacén es entrada NO confiable y se valida clave a clave (hay recorrido con un enum inventado que no rompe el arranque). **Y el aviso que no se disimula:** el orquestador Tauri sirve la interfaz en el **primer puerto libre del tramo 3000..3011**, y `localStorage` está particionado por origen — si algo ocupa el 3000, las preferencias dejan de verse. La degradación es benigna y queda declarada; la salida buena (guardarlas en el backend) es otra iteración. **NO se restaura la pantalla de bienvenida ni la vista activa**, y es una decisión: saltarse el portón cambia la primera impresión del producto y devolver al usuario a «figura 3D» sin modelo lo deja mirando un visor vacío. **La fase se cierra sin dejar su nombre en deudas ajenas**: había **5 entradas** de listas toleradas que decían «Dueña: Fase 13» y las cinco se revisaron y devolvieron con motivo escrito — y una de ellas estaba asignada por una **colisión de palabra** (`HistoryRun` decía «la que toca el historial», refiriéndose al historial de CORRIDAS, y el de esta fase es el de DESHACER). Hay guard que impide que vuelva a haber una. **Además se cierran los DOS rojos heredados** que arrastraban dos fases: `TQ_API_KEY` sin declarar (deuda de la Fase 11; se cierra porque el guard nuevo entra en el MISMO paso de CI y añadir un test a un paso ya rojo es no tener gate) y el huérfano `Solver` (deuda de la Fase 8; se declara como contrato-sin-enforcar, que es la salida 3 del propio mensaje del test). Gate: **24/24** del guard nuevo · **8/8** recorridos Playwright de la fase y **36/36** de la suite completa, regresión visual incluida · **260 tests** de los guards de CI en verde · tsc **0** · eslint **0** · `next build` OK · `ast_budgets`/`deps_closure`/`duplication`/tipos generados OK · **7 mutaciones verificadas**, y una de ellas destapó que **mi propio guard era inerte**: comprobaba si el nombre del filtro de foco aparecía en el fichero, así que bastaba dejar el `import` sin la llamada para que pasara. Reparado y re-mutado.)

**CERRADAS: 1 a 14 — EL PLAN §10 ESTÁ COMPLETO.** La **Fase 14** (2026-08-21) cerró **ABRIENDO**, y por muy poco: medida con el cableado que había, la respuesta era la de la Fase 4 —**no mejora**— y la fase llegó a estar escrita con ese veredicto. Lo que la cambió fue separar dos hipótesis que dan el MISMO número: que falle la idea, o que falle el **término del funcional** donde entra. Era lo segundo. Lo que faltaba tampoco era el cableado —la Fase 7.2 ya inyectaba φ como `m_ref`— sino **el interruptor**: `implicit_geology` no estaba en la allowlist del paquete y `merge_config` descartaba la clave **en silencio**, mientras los contactos litológicos ya viajaban enteros en `#BOREHOLES`. El hecho que gobierna la fase: `L·1 = 0` **exacto**, de donde un prior constante es **exactamente inerte** y las dos densidades **no son perillas independientes** (sólo actúa su diferencia). El hallazgo del campo: con contactos a una sola profundidad el HRBF **degenera a un plano infinito** — 1 sondaje ⇒ φ ≥ 0 en el **85 %** de la malla a **403 m** del único collar, y tres sondajes al mismo nivel dan φ **idéntico** (2,5e-13). **La medición, sobre dique inclinado con anti-inverse-crime ×3 y 25 semillas pareadas:** por la **suavidad** (cableado histórico) el prior PIERDE en PR-AUC 0/25; por el **smallness** GANA **25/25 en las cuatro métricas** (PR-AUC +0,250, IoU +0,228) y **la geología FALSA pasa a ser el peor brazo** (0/25, −0,382), que es la firma de un término que premia acertar la geometría y no «tener un prior». Y **el usuario no tiene que acertar la densidad**: equivocarla ×2 o ×0,5 sigue ganando 25/25. Por eso el default es `binding="smallness"`, y ese default **no cambia el resultado de nadie**: antes de esta fase la clave se descartaba en la allowlist, así que no existe una sola corrida histórica con este prior encendido. El cableado histórico se conserva como `binding="smoothness"`, byte-idéntico y con test. **Dos acoplamientos que el cambio destapó:** la «inversión 1» del DOI **es** la corrida principal, así que la pass-2 tiene que llevar el mismo binding o el índice mezcla dos cosas; y `_run_lsqr_with_heartbeat` es paso obligatorio del camino de producción —un parámetro no declarado ahí llega al motor por los tests y NO por el usuario, el mismo tropiezo que `anchor_mode` en la Fase 2—, y lo delató la suite de la **Fase 11** poniéndose roja. **Lo que NO está medido, dicho antes de que alguien lo cite de más:** un mundo, una λ, tres sondajes que sí cortan el cuerpo; **150 inversiones**, no las 3.450 de la Fase 4. Alcanza para elegir el default de un interruptor nuevo, no para prometer un porcentaje. **Los dos rojos heredados que arrastraban dos fases están CERRADOS por la Fase 13**: `TQ_API_KEY` quedó declarada en el registro de la Fase 5 (con sonda propia: la lee `terraquantum/_session.py`, no `core/config.py`) y el huérfano `Solver` de la Fase 8 quedó declarado en `HUERFANOS_TOLERADOS` como contrato-sin-enforcar — los cuatro solvers ya devuelven la tupla que describe; lo que falta es que alguien tipe contra ella, y eso no es una fase de frontend. **Lo que la Fase 13 midió y NO arregló, con nombre:** las **~19 perillas que `Scene3D` lee y ningún control puede mover** (`showVoxels`, `visualLayer`, `voxelOpacity`, `voxelScale`, `minTargetScore`, `minAnomalyIntensity`, `minDensityAnomalyScore`, `showAnomalyEnvelope`, `anomalyEnvelopePercent`, `showFloor`, `showTerrain`, `terrainOpacity`, `terrainVerticalExaggeration`, `showBoundingBox`, `showHostVolume`, `hostVolumeOpacity`, `showLegend`, `sliceThickness`, `doiThreshold`) — cablearlas es construir un panel de ~19 controles, que es una funcionalidad de UI y no undo/redo; quedan clasificadas una a una en `store/deshacible.ts`, así que **el número no puede crecer en silencio**. También quedan con nombre: **7 entradas** de listas toleradas que siguen esperando a la **Fase 11**, ya cerrada (deuda ajena, medida por el test de control de la Fase 13); **H-34**, el colormap Turbo en magnetometría, que §9H.2 llama el gap que más cuesta en una demo y **ninguna de las 14 fases reclama**; y que cambiar de pestaña **resetea los 41 parámetros de preparación**, porque `PreparacionView` se desmonta — arreglarlo es subir ese estado al store, un refactor que el repositorio prohíbe hacer de paso. La Fase 11 deja con nombre lo que NO arregló: los tres defectos H-F11-1/2/3 de arriba (ingesta, esquema y persistencia — tocarlos cambia el camino dorado de todos los usuarios y no era su alcance), y **20 modelos de respuesta** que cumplen la condición para declarar sus defaults como serializados y quedan fuera por no ser deuda de esta fase (`Project*`, `Spectral*`, `Terrain*`, `Favorability*`, `VoxelData`, `BlockModelResponse`): hacerlos todos habría sido el refactor global que el repositorio prohíbe. La Fase 8 deja además, medido y con nombre, lo que NO entró en sus cuatro pasos: `solve_magnetic_inversion_lsqr` (812 LOC / CC 116), `_import_gravity_csv_v1_impl` (777 / CC 181

### Plantilla de gate de fase (obligatoria desde la Fase 9)

Ninguna fase se declara cerrada sin responder estas cuatro, **con evidencia
medida** y no con una afirmación:

1. **¿Qué puede hacer o ver un usuario desde la interfaz que antes no podía?**
   Si la respuesta es «nada», decirlo explícitamente y justificar por qué (hay
   fases legítimamente internas: la 3, la 6 y la 8 lo son). Lo que no vale es no
   hacerse la pregunta — es así como pasaron los gates de F5, F7 y F8.
2. **¿Todo lo que la fase publica tiene consumidor?** Lo mide
   `tests/test_fase9_camino_de_usuario.py` en los tres eslabones. Una excepción es
   aceptable; una excepción **sin motivo escrito y fase dueña**, no.
3. **¿Cada valor de cada enumerado nuevo está ejercitado?** Patrón de
   `test_fase1_literal_dispatch.py`.
4. **¿El gate falla si se rompe lo que dice defender?** Verificado por
   **mutación**, no por lectura. La Fase 3 encontró un gate de física que pasaba
   con el bug dentro; la Fase 6, un guard que se anulaba a sí mismo.

**Un cambio de orden respecto a la tabla original, y su motivo:** la Fase 4 (depth-weighting) sube por delante de la 5 (superficie de configuración). Antes iban al revés porque la 5 es más barata; pero la 4 es **P0** y la 5 es **P2**, y una fase barata no justifica retrasar la única pregunta abierta sobre qué producto se tiene. El resto del orden es el que ya fijaba la tabla de la 1ª entrega.

**Las Fases 3, 5 y 6 pueden empezar hoy mismo**: son baratas, de riesgo casi nulo, y son las que impiden que los hallazgos vuelvan.

## Camino crítico

```
              ┌─ FASE 3 (red de seguridad: CI) ─┐   ← empezar YA, habilita todo lo demás
              │   + FASE 5 (superficie config)  │
              ▼                                 ▼
FASE 4 (medir W_z) ──► FASE 7 (extraer motor común) ──► FASE 8 (partir la espina)
     │                        ▲                                    │
     │   el CABLEADO de 4 ────┘  (H-9: si no, se arregla 2 veces)  ▼
     │                                                     FASE 14 (RBF) / 2ª física
     │
FASE 6 (limpieza)  FASE 9 (UI de F7)  FASE 12 (OMF)  FASE 10 (contratos) ─► FASE 13 (undo)
   ↑ paralelas entre sí y con todo lo anterior; la 6 es la de menor riesgo del plan
```

**Las Fases 1 y 2 no aparecen en el diagrama porque no dependen de nada ni bloquean nada**: son P0 por consecuencia, no por posición topológica. Se hacen primero porque cada día que pasan sin arreglarse es un día en que el producto puede entregar un resultado equivocado con cara de correcto.

**Lo que cambió respecto a la 1ª entrega:** la *medición* de la Fase 4 sigue sin dependencias y debe empezar primero. Pero su **cableado** ahora depende de la Fase 7, porque H-9 demostró que la cadena de pesos está duplicada en magnetometría. Y las Fases 3 y 5 subieron de prioridad: son baratas y son las que evitan que los hallazgos vuelvan.

**Instrumento de medición.** La Fase 4 y las byte-identidades de las Fases 7 y 8 exigen medir contra verdad conocida con anti-inverse-crime. Ese instrumento **ya no hay que improvisarlo**: es el Validation Framework de `docs/07_VALIDATION_FRAMEWORK.md`, construido después de esta auditoría precisamente para eso.

---

## FASE 1 — Los tres bugs de confianza del camino dorado · **S** · 🔴 **P0**

*(antes «Fase L» — renumerada para que el rotulo sea el orden de ejecucion.)*

*(Fase nueva, derivada de H-28, H-29 y H-27. **Es la de mayor valor por unidad de esfuerzo de todo el plan**: son pocas líneas y eliminan tres formas de entregar un resultado equivocado con cara de correcto.)*

**Objetivo.** Que sea imposible que el usuario vea un resultado que no corresponde a sus datos actuales.

**Justificación.** Los tres hallazgos comparten consecuencia: el producto muestra algo válido en apariencia que no corresponde a la realidad del momento. En una herramienta de targeting de perforación, eso es el daño reputacional máximo — y ninguno de los tres requiere tocar física.

**Trabajo.**
1. **H-28** — Llamar a la limpieza que ya existe: al cambiar cualquier archivo en `PrepPanel`, invalidar `model`/`show3D` (o mover `resetExplorationState` al store y llamarla desde ambos manejadores). **Alternativa más robusta y recomendada:** que el modelo lleve el identificador de la corrida que lo originó y la vista 3D se niegue a pintarlo si no coincide con la activa. Convierte una disciplina en un invariante.
   > **Reencuadre tras la 10ª pasada (H-36):** esa alternativa no es un parche defensivo — **es la versión mínima del patrón de "datos evaluados" que el informe 14 documenta como canónico** (Depsgraph de Blender: el dato derivado es de solo lectura y pertenece a una evaluación; si la fuente cambia, es inválido por construcción). Implementarla así, y no como una llamada de limpieza más, deja el camino abierto al recómputo incremental de F11 sin rediseñar nada después. **Es la misma línea de código, con una intención distinta.**
2. **H-29** — Resetear `acknowledgeSpatialRisk` y `acknowledgeRegionalScale` en **ambos** manejadores de archivo (hoy solo en el de gravimetría), y hacer que `handleValidate` valide **todos** los archivos que van a entrar al paquete, no solo el último tocado.
3. **H-27** — Emitir el fallback de topografía plana por el canal `warnings[]` que ya existe, y montar `WarningBanner` también en la vista de resultados.
4. **H-34** — Sustituir `TURBO_STOPS` por Viridis (o un mapa secuencial perceptualmente uniforme) en la capa de susceptibilidad magnética. **Es cambiar una constante** y elimina la incoherencia de que el mismo visor use dos escalas de distinta calidad perceptual.
5. **Invalidación "stale"** (§9H.2): si el usuario cambia un parámetro sin re-invertir, marcar el resultado en pantalla como desactualizado. Es la misma familia que H-28 y cierra el patrón entero de "mostrar algo que ya no corresponde".
6. **[H-37, el más urgente de esta fase] El modo `amplitude` fantasma.** Opción (a), inmediata: que el backend **rechace** `amplitude` con un error del catálogo ES y retirarlo del `<select>`. Opción (b), completa: cablear `solve_amplitude_inversion_lsqr`, que ya existe y tiene tests. **Lo que no es aceptable es dejarlo aceptando y mintiendo en el reporte.** Añadir un test que recorra **todos** los valores de cada `Literal` del esquema y verifique que el motor los despacha de verdad o los rechaza — el mismo patrón que la Fase 5 aplica a las variables de entorno.

**Estrategia de pruebas.** Tres recorridos Playwright, uno por bug: (a) cargar CSV A → invertir → volver a preparación → cargar CSV B → ir a la vista 3D y **verificar que no hay modelo**; (b) reconocer riesgo espacial con el archivo A → cambiar el magnético → **verificar que la casilla se desmarcó y el botón se deshabilitó**; (c) forzar el fallo de topografía → **verificar que el aviso aparece en pantalla**.

**Criterios de aceptación.** Los 3 recorridos verdes. `resetExplorationState` deja de ser código muerto (o desaparece). Ningún reconocimiento de riesgo sobrevive a un cambio de archivo.

**Riesgo de regresión.** Muy bajo: no toca física ni el motor. **Esfuerzo estimado: horas, no días.**

**Extra de coste casi nulo y alto retorno comercial** (§9H.3): adoptar el vocabulario **P10/P50/P90 y "dispersión de ensamble"** para presentar la incertidumbre que el motor **ya calcula** (B1/B2/B3, shuttle de null-space). No toca el motor: traduce el diferenciador al idioma que un consultor de recursos ya habla. De los tres rescates del informe 12, es el de mejor retorno por esfuerzo.

### ✅ EJECUTADA — 2026-08-08

*Dos iteraciones separadas (backend y frontend, regla de oro del repo). Riesgo cumplido: no se tocó física ni el motor.*

**Backend** — `core/errors.py`, `services/geophysics_service.py`, `api/geophysics_api.py`, 2 archivos de test nuevos:

| Ítem | Qué se hizo | Evidencia |
|---|---|---|
| **H-37** | `amplitude` **rechazado** con `INVERSION_MODE_UNAVAILABLE` (catálogo ES) antes de gastar un ciclo de solver, en el orquestador y en el motor magnético. `_use_remanence` ya no lo lista. | `test_fase1_confianza_camino_dorado.py` (16 tests) |
| **H-37b** ⚠️ nuevo | `lambda_strategy="lcurve"` prometía la esquina de la L-curve y caía en la rama de `chi2`; `select_lambda_lcurve` tiene **cero llamadores de producción**. Rechazado con `LAMBDA_STRATEGY_UNAVAILABLE`. | `test_fase1_literal_dispatch.py` (117 tests) |
| **H-27** | El fallback `flat_fallback` viaja ahora en `report.warnings[]` + `topography_degraded` (grav y mag) y se replica en `technicalSummary.warnings`. El caso `flat` (sin elevaciones declaradas) NO genera aviso: no es degradación inesperada. | ídem, con la interpolación de superficie forzada a fallar |

**Por qué H-37 se cerró rechazando y no cableando** (decisión medida, no pereza): `solve_amplitude_inversion_lsqr` existe y tiene tests, pero su contrato de entrada es la **amplitud |B| ≥ 0** del campo anómalo (valida `d_observed < 0` con `ValueError`). Producción sólo transporta **TMI**, que es una proyección con signo. Convertir TMI→|B| exige una transformación de componentes (Fourier / señal analítica) que **no existe en el repositorio**: cablear el solver alimentándolo con TMI sería el mismo pecado con otro disfraz. Es física nueva en el camino crítico y exige el rigor de medición de la Fase 4.

**El test de Literales encontró un segundo fantasma.** Ese era exactamente su propósito. `test_fase1_literal_dispatch.py` recorre los 19 valores `Literal` del esquema y exige que cada uno esté clasificado (`dispatched` / `declarative` / `rejected`) **con evidencia archivo+fragmento que se comprueba contra el código**, y que cada rechazo se ejecute de verdad en runtime. Un valor nuevo sin clasificar rompe la suite; una rama de despacho que desaparezca, también.

**Frontend** — `store/useAppStore.ts`, `PrepPanel.tsx`, `Exploration3DView.tsx`, `DatosView.tsx`, `HistorialView.tsx`, `MagneticRemanenceForm.tsx`, `lib/terraQuantumGeology.ts`, `lib/terraquantum/ColorPipeline.ts`, `workers/voxelBufferBuilder.worker.ts`, `lib/terraquantum/runWarnings.ts` (nuevo):

1. **H-28 — implementado como "dato evaluado", la alternativa recomendada.** El modelo se sella en `setModel` con `modelRunKey` = identidad de la corrida vigente, y la vista 3D **se niega a pintar** un modelo cuya clave no coincide con la corrida activa (y lo dice: *"Modelo no válido para los datos actuales"*). Además el store invalida `model`/`show3D`/`report`/heatmap/target al cambiar o limpiar la identidad de la corrida — el punto por el que pasan **todos** los caminos. `HistorialView` fija la corrida **antes** de cargar el modelo (el orden importa con el sello).
2. **H-29** — una única `resetOnFileChange()` compartida por ambos manejadores; el reconocimiento de riesgo caduca con cualquier cambio de archivo. `handleValidate` valida **todos** los archivos que entrarán al paquete y muestra el **peor** diagnóstico; la validación local de CSV y la condición de presencia del botón miran también ambos archivos.
3. **H-27 (mitad UI)** — `runWarnings.ts` extrae los avisos del reporte persistido y `WarningBanner` se monta en la vista 3D (donde se decide dónde perforar) y en el reporte de Datos. No se inventa nada: si el backend no emitió avisos, no aparece nada.
4. **H-34** — susceptibilidad migrada de Turbo a **Plasma** (secuencial, perceptualmente uniforme), en los **tres** sitios donde el colormap estaba duplicado. Se eligió Plasma y no Viridis para que las tres físicas sigan siendo distinguibles de un vistazo (Viridis=densidad, Plasma=susceptibilidad, Inferno=incertidumbre). **Y la leyenda dejó de mentir**: era Viridis fija incluso pintando susceptibilidad; ahora refleja la escala activa.
5. **Stale (§9H.2)** — huella de los parámetros de inversión en `PrepPanel`; si cambian con un modelo en pantalla se marca `resultIsStale` y el visor muestra *"Resultado desactualizado"*. Recargar el mismo run (cambio de resolución de display) **no** lo blanquea; sólo una corrida nueva.
6. **H-37 (UI)** — `amplitude` retirado del `<select>`, con nota que remite a MVI para remanencia de dirección desconocida y caída al default si llega un modo retirado.

**Criterios de aceptación.** ✅ `resetExplorationState` **desapareció** (era código muerto: nunca se llamó; su trabajo vive ahora en el store). ✅ Ningún reconocimiento de riesgo sobrevive a un cambio de archivo. ✅ Recorridos de aceptación en `e2e/fase1_confianza.spec.ts` (los 3 de la fase + stale + "sin degradación no se inventa aviso"), con el backend sustituido en la frontera HTTP: son invariantes de interfaz, y una inversión real de minutos no los haría más ciertos — las mitades de backend están cubiertas por pytest.

**Lo que NO se hizo, y por qué.** El **extra P10/P50/P90** queda pendiente **a propósito**: el motor publica percentiles de σ por vóxel (`doiDiagnostics`, `ensembleUncertainty` p50/p95), que **no son** los cuantiles P10/P50/P90 de una cantidad de recurso. Renombrarlos en la interfaz sería fabricar estadística en el frontend — la misma clase de deshonestidad que esta fase cierra. Hacerlo bien exige que el ensemble null-space emita cuantiles reales por blanco: es trabajo de backend y va con el cableado de F8.1, no aquí.

---

---

## FASE 2 — Que el instalador falle en voz alta · **M** · 🔴 **P0**

*(antes «Fase K» — renumerada para que el rotulo sea el orden de ejecucion.)*

*(Fase nueva, derivada de H-17 a H-21 y H-23. **La más urgente del plan en términos comerciales.**)*

**Objetivo.** Que ningún fallo de arranque en la máquina de un cliente sea silencioso, y que el ciclo de vida de los sidecars sea correcto por construcción.

**Justificación.** El motor puede ser excelente y el producto igualmente invendible si no arranca y no lo dice. Hoy la disciplina de "nunca fallar en silencio" —aplicada con rigor ejemplar al pipeline de datos— **no llega al proceso de arranque**, que es justamente donde no hay desarrollador presente para diagnosticar.

**Dependencias.** Ninguna. Es Rust + un HTML de splash; no toca la física ni el frontend de la aplicación.

**Diseño propuesto.**
1. **Health-check real del backend** antes de navegar: pedir `/health` y validar la respuesta, no solo un `TcpStream::connect` (cierra H-19). Incluir un token generado al arrancar para distinguir el sidecar propio de un zombi.
2. **Splash con estados y errores**: sustituir el HTML estático por una vista que reciba eventos de Tauri (`iniciando backend` → `iniciando interfaz` → `listo` / `error: <causa en español> + [Ver logs] + [Reintentar]`). Cierra H-17.
3. **Job Object de Windows** (`CreateJobObject` + `JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE`): el SO mata los hijos aunque el shell muera de forma violenta. Cierra H-18 por construcción, no por convención.
4. **Detección de puerto ocupado antes de spawnear**, con mensaje accionable y opción de usar puerto alternativo.
5. **Ruta de logs visible** desde el splash y desde el menú de la app.
6. **Higiene de seguridad** (cierra H-15 y mitiga H-21): invertir el default de `TERRAQUANTUM_HOST` a `127.0.0.1` (Docker ya lo fija explícito, no rompe nada), y decidir sobre las 3 llamadas directas navegador→backend: enrutarlas por proxy o documentarlas como excepción consciente.
7. **Reproducibilidad** (H-23): pinear `pyinstaller`, fijar `.python-version`, poner techo a las 7 dependencias con `>=`, y actualizar el tamaño en `docs/04`.
8. **Cablear el updater** (H-20) o **declararlo explícitamente como no disponible** en la documentación. Ambas son respuestas válidas; la que no vale es dejarlo ambiguo.

**Estrategia de pruebas.** Es la parte más valiosa y la que hoy no existe: una **matriz de arranque adverso** en una VM Windows limpia — (a) puerto 8010 ocupado, (b) puerto 3000 ocupado, (c) backend renombrado (simula cuarentena de antivirus), (d) kill del shell a mitad de arranque, (e) kill durante una inversión, (f) segundo arranque tras cada caso anterior. **Criterio: en los 6 casos, mensaje claro en español y cero procesos huérfanos.**

**Criterios de aceptación.** Los 6 casos de la matriz pasan; `tasklist` limpio tras cada uno; el cronómetro de instalación en VM limpia (pendiente declarado de F7) se mide por fin.

**Riesgo de regresión.** Bajo sobre la física (no la toca). Medio sobre el arranque mismo — por eso la matriz adversa es el gate, no un smoke test.

### ✅ EJECUTADA — 2026-08-10

*Tres iteraciones separadas (backend, shell de escritorio, frontend), regla de oro del repo. Riesgo cumplido: no se tocó física ni el motor — cero cambios en `exploration/`.*

#### Iteración 1 — Backend

`core/config.py`, `api/system_api.py`, `.env.example`, `requirements.txt`, `requirements-build.txt` (nuevo), `.python-version` (nuevo), `tests/test_fase2_arranque.py` (nuevo):

| Ítem | Qué se hizo | Evidencia |
|---|---|---|
| **H-15** | Default de `TERRAQUANTUM_HOST` invertido a **`127.0.0.1`**. La API corre sin autenticación por defecto, así que el binding es la única barrera real; ahora lo es por construcción y no porque tres lanzadores se acuerden. Docker sigue pidiendo `0.0.0.0` **explícito** (compose + `CMD` del Dockerfile), y el test lo verifica leyendo esos archivos: si alguien borra esa línea, el contenedor dejaría de responder y la suite lo dice antes que el usuario. | `test_default_host_is_loopback`, `test_docker_declares_its_exposure_explicitly`, `test_desktop_launchers_pin_loopback` |
| **H-19 (mitad backend)** | `/health` publica **identidad**: `pid` siempre, e `instance_token` cuando el proceso padre lo declara por entorno. Sin token declarado **no se inventa uno** — el chequeo se degrada, no miente. | `test_health_echoes_instance_token`, `test_health_publishes_pid_and_no_token_when_unclaimed` |
| **H-23** | `pyinstaller==6.21.0` pineado en un `requirements-build.txt` aparte (no debe viajar al contenedor ni al entorno del usuario); `.python-version` = 3.14.4; techo de major en las 6 dependencias que usaban `>=` sin él, con la versión medida anotada. | `test_no_requirement_is_unbounded`, `test_build_toolchain_is_pinned_exactly`, `test_numeric_core_stays_pinned_exact` |

`TERRAQUANTUM_HOST` era una de las 29 variables que **ningún test ejercitaba** (H-11): a partir de aquí una regresión del default se ve. **12/12 tests nuevos verdes.**

#### Iteración 2 — Shell de escritorio (Rust + splash)

`src-tauri/src/lib.rs` (reescrito, 1.195 líneas), `src-tauri/splash/index.html`, `tauri.conf.json`, `capabilities/default.json`:

| Ítem | Qué se hizo |
|---|---|
| **H-17** | El splash recibe eventos (`tq://boot`) y muestra el paso en curso; si algo falla, **la barra se detiene** (seguir animando era la mentira) y aparece la causa en español + **[Reintentar]** + **[Ver registros]** + [Cerrar]. Siete errores catalogados, cada uno con acción: `BACKEND_MISSING`, `BACKEND_SPAWN_FAILED`, `BACKEND_DEAD`, `BACKEND_TIMEOUT`, `FRONTEND_*`, `PORT_HIJACKED`, `PORTS_EXHAUSTED`. |
| **H-18** | Job Object de Windows con `JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE`, por **FFI directa a kernel32 y sin dependencias nuevas**. Si matan la app desde el Administrador de Tareas, el SO mata a los sidecars. Si el SO no lo permite, se registra el aviso y queda `taskkill` — degradación declarada, no silenciosa. |
| **H-19** | El shell genera un token por arranque, se lo pasa al backend y **compara contra `/health`**. El frontend se valida por `/api/backend-health`: esa respuesta demuestra a la vez que el sidecar Node es el nuestro **y** que está emparejado con nuestro backend. Sonda HTTP mínima escrita a mano (HTTP/1.0 sobre `TcpStream`) para no añadir dependencias por un GET a loopback. |
| **H-20** | Menú **Ayuda → «Buscar actualizaciones…»**, conducido desde Rust. Manual a propósito: un producto local-first no debe llamar a la red al arrancar. *(La **Fase 28** completó lo que faltaba: el endpoint apuntaba a un tercero y el aviso culpaba a la conexión del usuario. Ver `docs/04` §6.1.)* |
| **H-21 (shell)** | Puertos elegidos **antes** de spawnear; si el preferido está ocupado se usa el siguiente libre del tramo y se explica quién lo ocupaba. El puerto elegido viaja al sidecar Node por entorno. |
| Registros | Botón en el splash y menú **Ayuda → Ver registros / Abrir carpeta de datos**. |

**La decisión que hace auditable la fase: el diario de arranque.** Todo lo que se muestra en el splash se escribe a `%APPDATA%\TerraQuantum\logs\boot.jsonl` desde la **misma** función (`publish`), así que no pueden divergir. Sin eso, la matriz adversa exigiría pilotar una interfaz gráfica; con eso, el gate lee un archivo y **decide**.

**Higiene de permisos.** `withGlobalTauri` se activó para que el splash pueda escuchar eventos sin bundler. Es seguro porque la capability **no declara `remote`**: la aplicación servida en `http://localhost:3000` recibe el objeto pero la ACL rechaza cualquier llamada. Y se **retiró** `updater:default` de la capability: el updater ya no se invoca desde la interfaz, así que su superficie desde el webview sobra.

**9/9 tests unitarios de Rust** sobre lo que decide: parseo HTTP, veredicto de identidad (incluido el caso «un zombi de TerraQuantum responde igual de bien: sin token no vale»), elección de puerto y forma del evento que lee el gate. `cargo check`: 0 errores, 0 avisos propios.

> **Y a esos nueve tests no los corría nadie (medido por la Fase 28, 09-06).** Ni
> `.github/workflows/ci.yml` —que no tenía **un solo paso de cargo**— ni
> `check.ps1`, la puerta pre-push. Nueve tests escritos como gate y ejecutados
> por ninguna puerta durante 26 días: la variante más silenciosa de H-22, porque
> aquí ni siquiera hacía falta que alguien interpretara la salida — no había
> salida. Corregido: job `desktop-shell` en la CI y paso `[1b/4]` en `check.ps1`.
> Es la **cuarta** vez que aparece el patrón «una puerta que no corre» (Fases 3,
> 15, 27).

> **Un test flaky, cazado y corregido dentro de la fase.** La primera versión de los tests de puerto pedía un puerto efímero al sistema y afirmaba cosas sobre sus vecinos; pasó en la primera corrida y **falló en la segunda** — apareció justo porque el gate se corrió dos veces antes de declarar la fase cerrada. La decisión de qué puerto elegir se separó del sistema operativo (`choose_port_where` recibe el predicado de "libre"), y ahora hay dos tests: uno **determinista** sobre la lógica y otro con un socket real que sólo afirma lo que siempre es cierto — *nunca devuelve el puerto ocupado*. Un test que pasa «casi siempre» es peor que no tenerlo: enseña a ignorar la suite.

#### Iteración 3 — Frontend

3 rutas nuevas (`app/api/export-bundle`, `app/api/delete-run`, `app/api/project-footprint`), `app/api/terrain-texture/route.ts`, `app/api/_lib/backend.ts`, `lib/terraquantum/frontendApi.ts`, 10 proxies con la precedencia de entorno invertida, `scripts/check_client_backend_calls.mjs` (nuevo):

**H-21 se cerró enrutando, no documentando la excepción** — y la razón no es sólo de seguridad, es de **corrección medida**: desde esta fase el backend puede arrancar en un puerto alternativo, y `NEXT_PUBLIC_TERRAQUANTUM_BACKEND_URL` **se hornea en el bundle del navegador en tiempo de build**. Una llamada directa apuntaría entonces a *otro proceso* — el mismo fallo de identidad de H-19, pero servido al usuario como una descarga. `BACKEND_PUBLIC_URL` **desapareció**: el navegador ya no sabe dónde escucha el motor.

**Un segundo agujero de la misma familia, encontrado al medir:** diez proxies *de servidor* leían `NEXT_PUBLIC_TERRAQUANTUM_BACKEND_URL` **antes** que la variable de ejecución. En el build actual eso no muerde (se comprobó en los chunks compilados: la constante quedó como `process.env.TERRAQUANTUM_BACKEND_URL||"http://127.0.0.1:8010"`, es decir, la lectura de runtime sobrevivió porque no había `.env.local` al construir). Pero `start-frontend.bat` **crea** ese `.env.local`; construir después de usarlo habría clavado los diez proxies al 8010. Se invirtió la precedencia.

El guard `check_client_backend_calls.mjs` **decide** (exit 1) y está auto-verificado: sus reglas encuentran **7 ocurrencias** en la versión anterior de `frontendApi.ts` y **0** en la actual. `eslint` 0, `tsc --noEmit` 0, `npm run build` OK con las tres rutas nuevas presentes en el standalone.

#### Hallazgo nuevo de esta fase (no introducido por ella)

**El borrado de corridas apunta a un endpoint que no existe.** `deleteRun` llamaba a `DELETE /projects/{id}/runs/{run_id}`; **no hay ninguna ruta de borrado en `api/`** (verificado enumerando los decoradores de `project_api.py` e `history_api.py`). Devolvía 404 antes y devuelve 404 ahora: lo único que cambia es que ya no sale del navegador. **No se implementó** porque crear un endpoint de borrado es funcionalidad nueva fuera del alcance de esta fase, y porque borrar corridas de un cliente merece su propia decisión de diseño (¿papelera?, ¿confirmación doble?, ¿qué pasa con la corrida activa?). Queda anotado como deuda con nombre.

#### Verificación

**El gate: `scripts/f2_gate_boot_matrix.ps1` — PASA 6/6**, corrido tres veces a lo largo de la fase (la última sobre el binario que queda), medido contra la app **real** (`cargo build --release` con los sidecars recién reconstruidos: backend PyInstaller de 242,3 MB con el token de identidad, frontend standalone con las tres rutas nuevas). Diez arranques completos de la aplicación (cinco casos adversos + un segundo arranque tras cada uno):

| Caso | Qué se montó | Qué se comprobó |
|---|---|---|
| **0** | — | Guard estático: cero llamadas directas navegador→backend |
| **a** | Un listener real ocupando el 8010 | Aviso `BACKEND_PORT_FALLBACK` («el motor usará el 8011») **y llega a LISTO** — que llegue prueba el emparejamiento, porque la sonda del frontend exige el token del backend a través del proxy |
| **b** | Un listener real ocupando el 3000 | Aviso `FRONTEND_PORT_FALLBACK` y la ventana navega a `http://localhost:3001` |
| **c** | Backend renombrado (cuarentena de antivirus) | `BACKEND_MISSING` en español, con acción («Reinstala TerraQuantum y revisa la cuarentena del antivirus»), **sin espera infinita** |
| **d** | `Stop-Process -Force` del shell **a mitad** del arranque | Cero huérfanos — el Job Object cumplió |
| **e** | `Stop-Process -Force` con tráfico real en vuelo por ambos sidecars | Cero huérfanos |
| **f** | Un segundo arranque **después de cada caso** | Vuelve a LISTO las cinco veces |

En los cinco casos con arranque se compara el censo de `terraquantum-backend.exe`/`node.exe` antes y después: **cero procesos huérfanos**. Un gate que no ejecuta ningún caso (o que corre con `-Only`) **falla**: «verde por vacío» es la forma más común de que una puerta deje de proteger.

**El resto de la evidencia:** suite completa de backend **2.277 passed / 14 skipped / 0 failed** (59 min) · 12/12 tests nuevos de backend · 9/9 tests unitarios de Rust · **12/12 recorridos E2E de Playwright** contra el build de producción (incluye `HistorialView`, que es quien consume el proxy de footprint nuevo) · `cargo check` sin avisos propios · `eslint` 0 · `tsc --noEmit` 0 · `npm run build` OK · guard estático auto-verificado (7 ocurrencias en la versión anterior de `frontendApi.ts`, 0 en la actual).

**Lo que NO se hizo, y por qué.**
- **El botón de instalar la actualización.** La comprobación está cableada y es honesta cuando no hay red; la **instalación** no, porque no existe ningún release publicado contra el que probarla. Cablear un camino que no se puede ejercitar sería exactamente el patrón que H-20 denunció.
- **El cronómetro de instalación en VM Windows limpia** (pendiente heredado de F7) sigue pendiente: exige una máquina virgen, no esta. Lo que sí se puede afirmar ahora es lo que antes no: que en los modos de fallo que la matriz cubre el producto **dice** lo que pasa, en vez de animar una barra para siempre.
- **Los botones del splash no los pulsa nadie automáticamente.** El gate demuestra que se **llega** al estado de error y que ese estado lleva mensaje y acción; que al hacer clic en [Ver registros] se abra el explorador y que [Reintentar] rearranque no lo cubre ninguna prueba, porque haría falta un piloto de interfaz gráfica sobre la ventana nativa. Lo que sí está cubierto por construcción es que splash y diario **no pueden divergir**: salen de la misma función.
- **El caso (e) es una aproximación declarada.** El criterio decía «matar durante una inversión»; el gate mata con tráfico real en vuelo por ambos sidecars, no con una inversión completa (que exigiría un paquete de datos y minutos de cómputo). Lo que se prueba —el ciclo de vida de los procesos— no depende de qué esté calculando el backend. Está anotado en el propio script.

---

---

## FASE 3 — Red de seguridad real · **S** · 🟠 P1

*(antes «Fase C» — renumerada para que el rotulo sea el orden de ejecucion.)*

**Objetivo.** Que la CI defienda lo que la documentación promete.

**Justificación.** H-4 y H-5: la regresión física no corre y la CI compila directorios inexistentes sin fallar.

**Diseño propuesto.**
1. Corregir `ci.yml:28`: quitar `Camiones` y `workers`; añadir `|| exit 1` sobre una verificación de existencia previa, para que la deriva futura **falle ruidosamente**.
2. Añadir job `physics-regression` (nightly o pre-merge a `main`): `TQ_RUN_VALIDATION=1 pytest -m validation` + `f9_gate_regression.py`.
3. Añadir job `config-matrix`: recorrer los flags de `core/config.py` y verificar que cada camino arranca. **Esto caza H-2 automáticamente.**
4. Añadir el generativo de ingesta con N reducido (p. ej. 500 casos) al PR, y N completo al nightly.
5. Publicar métricas AST (LOC/CC máximos) como gate que **falla si empeoran** — así la Fase 8 no se deshace sola con el tiempo.
6. **Test de capas** (§9I.6, ~30 líneas con AST): falla si `core/` importa hacia arriba, si `exploration/` importa `services`/`api`, o si aparece dominio nuevo en el Core. Hoy la dirección de dependencias es limpia **por disciplina**; esto la hace limpia **por construcción**. El informe 14 insiste en que las reglas de visibilidad las imponga el build, no la voluntad humana.

**Criterios de aceptación.** CI roja si: la física regresiona, un flag documentado rompe, o una función supera los umbrales.

**Riesgo.** Bajo. Coste: minutos de CI.

### ✅ EJECUTADA — 2026-08-12

*Iteración de backend + infraestructura de CI. Cero cambios en `exploration/` y cero en el frontend de la aplicación (lo único que se tocó de `terraquantum-web` es una línea del job de CI que invoca la guarda estática de la Fase 2).*

**Lo que ahora defiende la CI**

| Pieza | Qué impide | Evidencia |
|---|---|---|
| `scripts/ci/compile_check.py` | Que la lista de paquetes se mantenga a mano y se pudra (**H-5**) | 4 tests; reproducido el fallo original |
| `tests/test_fase3_capas.py` | Que la dirección de dependencias se rompa (§9I) | 8 tests, grafo medido con AST |
| `scripts/ci/ast_budgets.py` + `ast_baseline.json` | Que la Fase 8 se deshaga sola | 7 tests; línea base medida |
| `scripts/ci/validation_inventory.py` + `GATES.json` | Que un diagnóstico se llame gate (**H-22**) | 65 scripts clasificados |
| ~~`tests/test_fase3_config_matrix.py`~~ → `tests/test_fase5_superficie_config.py` | Que un flag documentado rompa el arranque (**H-11**) | 29 tests / 22 variables → **154 tests / 42 variables** al fusionarse con la Fase 5 (la auditoría ya preveía la fusión) |
| Job `physics-regression-nightly` + canario en PR | Que la física regresione en silencio (**H-4**) | 6 tests de contabilidad |
| `core/config.py::_env_int` | Que un valor basura muera sin decir qué variable es | 4 tests |

**Cinco correcciones medidas a la propia auditoría** (el trabajo de la fase fue tanto medir como construir):

1. **El arreglo que la fase prescribía para H-4 no habría funcionado.** El texto decía «añadir job con `TQ_RUN_VALIDATION=1`». Medido: los 8 tests `validation` llevan **también** el marcador `slow`, así que `-m "not slow"` los deselecciona *antes* de que el skip de `conftest` entre en juego (`pytest -m "not slow and validation" --collect-only` → **0 tests**). Hay que invocarlos por nodeid y sin ese filtro. El canario del PR lo hace así.
2. **El generativo de ingesta YA corría en la CI.** La auditoría lo daba «fuera de la CI por tiempo»; `test_ingesta_generativa.py` no lleva marca `slow` y su default es `TQ_GEN_N=400`, así que cada PR ya lo ejecutaba. Lo que faltaba era la pasada larga: va en el nocturno con N=5.000.
3. **La CI resolvía un *major* distinto de una dependencia científica.** `ci.yml` fijaba Python 3.11 a mano; `zarr==3.2.1` exige `>=3.12`, así que pip resolvía zarr 2.x. La CI validaba un árbol de dependencias que no llega al cliente. Ahora lee `terraquantum-backend/.python-version`, el mismo archivo que declara el intérprete que se empaqueta.
4. **La marca `slow` dejó de separar nada.** Medido: `-m "not slow"` selecciona **2.256 de 2.290** tests. El comentario de la CI prometía «~900 tests, ~25 min» cuando la suite completa tarda ~60 min. Corregido en el propio archivo.
5. **El coste del gate de física no es reproducible.** Los dos reportes guardados del propio gate declaran **1.972 s** y **24.852 s** para el mismo `PASS 6/6`, con DO-27 dominando en ambos. Por eso el job nocturno lleva `timeout-minutes: 330` (bajo el tope de 6 h de los runners alojados) y publica el reporte **aunque falle**.

**El hallazgo que más importa, y no es de CI.** `.env.local` de esta máquina fijaba `TERRAQUANTUM_HOST=0.0.0.0` — herencia de cuando ese era el default del código. La Fase 2 hizo seguro el **default**, y el producto empaquetado nunca se vio afectado (el orquestador fija la variable explícitamente y `main.py` sólo rellena claves *ausentes*), pero en la máquina de desarrollo el motor escuchaba en toda la red **sin autenticación**. Dos respuestas, no una: el archivo se corrigió a `127.0.0.1` (con autorización), **y** el backend ahora lo **dice en voz alta en cada arranque** cuando escucha fuera de loopback con `TQ_AUTH_ENABLED=false` — porque el próximo `.env.local` de la próxima máquina no lo va a arreglar nadie.

**H-7, cerrado de paso.** `credenciales_gee.json.REVOKED_2026-06-03` seguía **rastreado por git** con un bloque `BEGIN PRIVATE KEY` real de la cuenta de servicio `terraquantum-satelite@…`. Está revocada, pero viajaba en cada clon. Se sacó del índice y del árbol de trabajo, y se corrigió la causa: `.gitignore` cubría el nombre **exacto** `credenciales_gee.json`, de modo que cualquier renombrado volvía a ser rastreable. Ahora cubre `credenciales_gee.json.*` y `credenciales_gee*.json`. **Pendiente y de decisión humana:** purgar el blob de la *historia* exige reescribirla y forzar el push, lo que rompe todo clon existente. Con la clave ya revocada el riesgo residual es de higiene, no de acceso.

**Segundo hallazgo de paso:** `MAGNETIC_SUSCEPTIBILITY_PRESETS` (`core/config.py:129`) es una tabla de dominio dentro del Core **sin ningún consumidor de producción** — su única referencia fuera de la definición es un test. Queda anotada como deuda, no se borra aquí (borrar código de dominio es Fase 6, ya cerrada, y toca un test ajeno). — **✅ CERRADO el 2026-08-14 en el cierre de la Fase 6**: borrada la tabla y el test que la validaba contra sí misma. Ver el registro `### ✅ CERRADA DEL TODO` de la Fase 6.

**La foto de complejidad que congela esta fase** (medida con AST, línea base commiteada):

| Paquete | Archivos | LOC | Función más larga | CC máx |
|---|---:|---:|---:|---:|
| services | 54 | 27.592 | 2.013 | **183** |
| exploration | 15 | 10.777 | 1.039 | 143 |
| api | 22 | 6.102 | 927 | 165 |
| schemas | 9 | 2.278 | 19 | 7 |
| core | 11 | 1.774 | 67 | 19 |
| reporting | 2 | 1.771 | 488 | 32 |
| middleware | 2 | 53 | 28 | 8 |

`run_geophysics_inversion` — **2.013 líneas, complejidad 183** — es la espina dorsal que la Fase 8 va a partir. A partir de ahora no puede crecer más de un 5% sin que la CI lo diga.

**H-22, cerrado sin reescribir 43 scripts.** Los 65 archivos de `scripts/validation/` están clasificados en `GATES.json`: **22 gates** (deciden, con salida ≠ 0 verificada por AST), **33 diagnósticos**, **3 bibliotecas**, **7 colecciones de tests**. El gate falla si aparece un script sin clasificar, si algo declarado `gate` no puede fallar, o si la documentación llama «gate» a un diagnóstico. Construyéndolo saltó un caso real que resultó ser falso positivo —`docs/01:439` nombra `f9_gate_regression.py` y `f9_report.py` en la misma frase— y el detector se afinó para no acusar cuando la palabra ya tiene dueño en la línea.

**El gate de física ya no confunde «no hay dato» con «la física regresionó».** DO-27 (110,8 MB) y Raglan (7,8 MB) ya estaban versionados; San Nicolás y LdM vivían sólo bajo `data/projects/`, que `.gitignore` excluye, así que en un checkout limpio daban **FALLO por ausencia de datos** — y un gate rojo por costumbre deja de leerse. Dos arreglos, en este orden:

1. El veredicto habla **sólo de lo evaluado** y el reporte dice qué no se evaluó. Un dataset **versionado** que desaparezca sigue siendo FALLO: no hay puerta trasera para apagar el gate borrando archivos.
2. Se versionaron las observaciones de San Nicolás y LdM como fixtures (`tests/fixtures/f9/`, **122 KB**), con un test que comprueba que son **idénticas** a la corrida canónica. La resolución prefiere la corrida viva de `data/projects/` cuando existe —para que en la máquina de desarrollo se siga midiendo el artefacto original— y cae a la fixture en un checkout limpio.

**Resultado: el nocturno evalúa los 6 casos, no 4.** Y no por construcción sino **medido**: se corrieron los dos casos por ambas rutas, con el motor real, y dan el mismo número — LdM χ² = **0,98694914119** por la corrida viva y por la fixture (13,7 s), San Nicolás misfit **1,51 %** por ambas (56,7 s). Si la fixture se desviara de la corrida canónica, el gate se convertiría en una regresión contra sí mismo; por eso además hay un test que compara los dos archivos.

**Lo que NO se hizo, y por qué.**
- ~~**No puedo afirmar que la CI pase.**~~ → **Resuelto el 2026-08-13. La respuesta era NO: la CI estaba en rojo.** Ver el cierre más abajo.
- **La matriz de configuración prueba que los flags ARRANCAN, no que hagan lo que prometen.** `USE_BOUNDED_SOLVER`, `USE_PROJECTED_SOLVER` y `USE_LSMR_LARGE` podrían estar tan inertes como lo estuvieron las perillas wavelet, y esta sonda no lo vería: eso exige una inversión medida y va con la Fase 5.
- **El gate de arranque de la Fase 2 no está en la CI**: necesita Windows, la app compilada y ~1 GB de sidecars. Sigue siendo un gate de máquina de desarrollo, y así está declarado.

---

### ✅ CERRADA DEL TODO — 2026-08-13

*La entrega del 08-12 dejó una frase abierta: «no puedo afirmar que la CI pase». Esta iteración la responde midiendo, y la respuesta obliga a corregir la anterior: **la CI no pasaba**. Backend + CI otra vez; cero cambios en el frontend de la aplicación.*

**Cómo se midió sin runner y sin `gh`.** Se reprodujo el checkout del runner con un `git clone` de la rama en HEAD —sólo archivos versionados, sin `.env.local`, sin `data/projects/`— y se ejecutó cada paso de `ci.yml` sobre él. Lo que un clon en Windows no puede ver (el sistema operativo y, sobre todo, **el conjunto de paquetes instalados**) se cubrió aparte: el manifiesto de `actions/setup-python` para saber si el intérprete existe, la API de PyPI para saber si las ruedas existen, y dos simulaciones del entorno del runner.

**Lo que salió bien y ya no hay que volver a preguntarse:**
- `python-version-file` apunta a **3.14.4**, y 3.14.4 **existe** en el manifiesto de `actions/setup-python` para linux x64 (22.04 y 24.04). El paso no va a fallar.
- Las **30 dependencias** de `requirements.txt` tienen rueda linux-cp314 (o `py3-none-any`) en PyPI. `opentelemetry-instrumentation-fastapi==0.63b1` es una prerelease publicada y válida, no un pin roto.
- Job `frontend` **verde de verdad**: `npm ci`, `npm run lint` (0 errores, 23 avisos), la guarda cliente→backend de la Fase 2 y `npm run build`, con los códigos de salida leídos bien.
- Sobre el clon prístino pasan `compile_check`, `ast_budgets`, `validation_inventory`, los cuatro ficheros de guardas (32 passed / 2 skipped) y el canario de física (7,7 s). Y la suite entera del job de PR: **2.312 passed / 8 skipped / 34 deselected, 0 fallos** sobre el checkout limpio. **Ningún test depende de datos gitignorados**: la hipótesis de que el checkout limpio rompería la suite era falsa.

  **Y ese verde es exactamente el problema.** Esas 2.312 pruebas pasan porque corren en Windows y contra los paquetes que hay instalados en esta máquina — que no son los que instala el runner. Las dos causas de rojo de abajo son, por construcción, invisibles para esta corrida. Un pleno de verde no dice «la CI pasa»: dice «la CI pasa *aquí*», y esa confusión es la que la Fase 3 existe para eliminar. (El reloj de esa corrida —16 h 45 m— no es una estimación de coste: la máquina estaba haciendo otras diez cosas a la vez. La medición honesta del coste sigue siendo la del 08-11: ~60 min.)

**DOS CAUSAS MEDIDAS DE CI EN ROJO, invisibles en esta máquina.** Las dos son la misma enfermedad que la fase ya había diagnosticado para el intérprete —la CI instala un árbol distinto del que hay en desarrollo— y que el arreglo del 08-12 sólo curó a medias: fijó la **versión de Python** y dejó suelto el **conjunto de paquetes**.

1. **`psutil` no estaba declarada.** Llegaba de rebote como transitiva de `distributed`, que la Fase 6/H-14 eliminó con razón el 08-09. El código la sigue importando. Simulando un runner sin ella (bloqueando el módulo en `sys.meta_path`): **6 tests de `test_kernel_sparsity_memory.py` mueren con `ModuleNotFoundError` → job `backend` en rojo**. Y hay un segundo daño, peor y silencioso: el `except Exception` de `exploration/gravimetry.py` deja `available = None` y **la red de seguridad de memoria del kernel (`SOLVER_KERNEL_TOO_DENSE`) se apaga sin decir nada** — un fallback que finge, que es la causa #1 del propio informe industrial del proyecto. Declarada con techo de major (H-23).
2. **`PyWavelets` está declarada y NO instalada aquí.** O sea: la CI la instala y ejecuta dos tests que **en esta máquina no se han corrido nunca**. Medido con pywt 1.9.0 y el numpy del propio entorno: `test_wavelet_compression_ratio` retiene **98,2%** donde exige <15%, y `test_wavelet_forward_error` da **0,615%** donde exige <0,5%. El bloque wavelet de la Fase 10 no cumple su propio criterio §10.6.1. No se arregla aquí (no tiene llamadores de producción, Fase 6/H-13, y tocar el algoritmo es física) pero tampoco se esconde: van como `xfail(strict=True)` con el número medido, así que la CI queda verde con el fallo **registrado** y un futuro arreglo produce XPASS y obliga a actualizar la promesa. De paso: estaban escritos como `if not _PYWT: print(...); return`, que reportaba **PASSED sin ejecutar nada**; ahora son `skipif` y se ven SKIPPED. — **✅ RESUELTO el 2026-08-14 en el cierre de la Fase 6**: `exploration/jacobian_wavelet.py`, sus tres tests y la dependencia `PyWavelets` fueron BORRADOS. Un `xfail(strict=True)` es honesto pero no es un final: deja registrada indefinidamente una promesa incumplida de código que nadie llama. Como cumplirla exigía rehacer el algoritmo (física, no CI), la salida correcta era la otra mitad de la regla de la Fase 6.

**El criterio de aceptación, puesto a prueba por mutación.** «CI roja si: la física regresiona, un flag documentado rompe, o una función supera los umbrales.» Nadie lo había comprobado — los tests existentes verifican que los gates **corren**, que no es lo mismo. Seis mutaciones reversibles sobre el clon, con su código de salida:

| mutación | gate | veredicto |
|---|---|---|
| `G` 6,67430e-11 → 7,00000e-11 (+4,9%) | canario de física | **PASA** ❌ |
| variable de entorno nueva sin declarar | matriz de configuración | FALLA ✔ |
| `CSV_MAX_BYTES` renombrada | matriz de configuración | FALLA ✔ |
| +300 ramas en `services/` | presupuestos AST | FALLA ✔ |
| `core/` importa `services/` | test de capas | FALLA ✔ |
| script nuevo sin clasificar | inventario de gates | FALLA ✔ |
| desaparece un paquete declarado | compile check | FALLA ✔ |

**Seis de siete defienden. El que no, es el de física** — y es el primero de los tres criterios.

**Por qué el canario es ciego, que no es lo que yo creía.** La explicación fácil («Pearson es invariante al escalado») es incompleta. Se midió el mecanismo: con `G` mutada, la señal sintética sube exactamente un +4,88%… y la inversión usa **ese mismo kernel**, así que la constante se cancela y **ningún** número se mueve — ni `pearson_r` (0,7259), ni el misfit (0,654%), ni χ². El benchmark lleva el cartel «ANTI-INVERSE CRIME: mallas y operadores distintos», y es cierto para la malla; pero las **constantes son las mismas a ambos lados**. En ese eje el crimen inverso sigue ahí. Se comprobó además que el canario **sí** ve una regresión de forma (λ_spatial×500 → falla), así que la frontera queda clara: ve forma, no ve escala.

**Y un tercer hallazgo que sale del mismo experimento:** con **W_z apagado** (exponente 0) el canario tampoco se mueve — 0,7259 idéntico. Es coherente con lo que el Punto 4 ya midió (`depth_beta` es inerte, `Ws` lo absorbe), pero nadie lo había propagado hasta aquí: **la nota del propio canario decía que servía para vigilar la degradación de W_z**. Corregida con el número.

**Lo construido para cerrarlo** (todo decide, exit≠0):
- **`tests/test_fase3_calibracion_absoluta.py`** — contrasta el operador forward de producción contra la masa puntual analítica (fórmula escrita en el test, con la G de CODATA independiente del motor) en cuatro geometrías y tres profundidades. Verificado: coinciden a **8 cifras**, así que la tolerancia de 1e-4 es ~500 veces más estrecha que la mutación que el canario deja pasar. **Con la mutación de `G`, este archivo se pone rojo (5 de 6 tests).** Caza de un golpe la clase entera: constante equivocada, conversión t/m³↔kg/m³ perdida, factor 1e-5 de mGal colado, eje/componente cambiado. No es teórico: el proyecto ya se descalibró así **dos veces** (mGal×1e-5 en DO-27, doble Bouguer en `9045719`), y ninguna de las dos habría puesto roja la CI.
- **`scripts/ci/deps_closure.py`** — el arreglo de la CLASE, no del caso. Calcula el cierre transitivo de `requirements.txt` y falla si el código importa algo que ese cierre no cubre. Probado por mutación: quitando `psutil` del manifiesto, el gate lo señala y **dice por qué no se ve en local** («instalada AQUI … por eso no lo ves fallar»). Los imports opcionales bajo guarda (`pyopenvdb`, `simpeg`, `discretize`) se declaran con su motivo, al estilo del inventario de H-22: uno nuevo sin declarar rompe el gate a propósito. Corre en `ci.yml` y en `check.ps1` — y es en `check.ps1` donde de verdad trabaja, porque en el runner lo instalado *es* el cierre.
- **`branches: ["*"]` → `["**"]`** en el disparador de push. En los filtros de GitHub Actions `*` **no cruza la barra**: un push a `fix/algo` o `feature/x` no disparaba ningún job. La red existía y no cubría el nombre de rama más común del oficio.
- **Paso nocturno para los tests `validation` que no corría nadie.** El diseño pedía `pytest -m validation` entero. Medido: los 8 llevan también `slow` (el job de PR los deselecciona) y el gate F9 es *main()-only* —no invoca pytest—, así que de los 8 sólo se ejecutaba **uno**, el canario por nodeid. Los 5 de `test_f9_physics_regression` los cubre en sustancia el gate (mismos datasets, mismo motor; duplicarlos costaría entre 33 min y 6,9 h); los **2 de `test_depth_prior_service` no los cubría nada** y ahora corren en el nocturno (**8 min 09 s medidos, ambos pasan**). Un test nuevo con marca `validation` que quede huérfano rompe `test_fase3_ci_guards.py`.

**Dos cosas que parecen huecos y no lo son, para que nadie las persiga otra vez:**
- En un checkout limpio, `test_fase3_f9_no_evaluado.py` deja **2 skipped**: son los que comparan la fixture contra la corrida viva, y en un runner no hay corrida viva que comparar. Es el diseño del 08-12 funcionando —esa comparación es un gate de la máquina de Martín— y los otros 8 sí corren.
- Los avisos de `npm run lint` (23) no rompen nada: el job exige **0 errores**, y hay 0.

**Riesgo residual medido, no cerrado.** Los rangos con techo de major (H-23) hacen que la CI instale versiones distintas de las de esta máquina: **zarr 3.2.1 aquí → 3.3.0 en la CI**, **dask 2026.3.0 → 2026.7.1**, y **PyWavelets 1.9.0 en la CI donde aquí no hay ninguna**. Los rangos son deliberados y no se tocan; pero eso significa que el primer runner ejecuta código contra minors que aquí nadie ha probado. Es exactamente por donde salió la causa nº 2. *(El caso `PyWavelets` dejó de existir el 2026-08-14: la dependencia se eliminó al cerrar la Fase 6. El riesgo general —zarr, dask— sigue vigente tal cual.)*

**Lo que sigue sin poder afirmarse, dicho claro.** Todo esto se midió reproduciendo el runner, no en el runner: no hay `gh` en esta máquina y **el push sigue pendiente de decisión humana**, porque la historia se reescribió el 08-12 para purgar el blob de H-7 y publicarla exige `--force`, que rompe cualquier clon existente. Lo que ya no está en el aire es lo que se preguntaba el 08-12: las dos causas de rojo estaban **dentro** del árbol, no en el runner, y se corrigieron con el número delante.

---

---

## FASE 4 — Resolver el depth-weighting inerte · **S** · 🔴 P0

*(antes «Fase A» — renumerada para que el rotulo sea el orden de ejecucion.)*

**Objetivo.** Determinar, midiendo, si separar el precondicionador del peso de modelo recupera capacidad de resolver profundidad.

**Justificación.** H-1 es la causa raíz común de tres hallazgos que el proyecto ya midió por separado sin explicarlos. Sin cerrarlo no se sabe qué producto se tiene: si la profundidad es recuperable, hay un producto nuevo; si no, se vende el límite con autoridad definitiva.

**Dependencias.** Ninguna. El harness ya existe (`error_budget.py`, `f9_regression_lib`).

> **Corregido tras la 4ª pasada:** en la primera versión escribí que H-9 obligaba a arreglar esto dos veces (gravedad y magnetometría). **Es falso y lo verifiqué**: `magnetometry.py` no tiene `Ws` y su depth-weighting funciona (§9D.1). H-1 es exclusivo de gravimetría.

> **Segunda corrección (5ª pasada):** una versión previa de esta fase abría con un paso "A.0" para medir un supuesto desajuste entre el selector de λ y el solver. **Ese desajuste no existe en producción** (§9D.2): el Morozov real escanea con el solver de producción. A.0 queda eliminado; la fase empieza directamente en A.1.

**Contexto que sí importa para A.1:** como producción elige λ ejecutando el solver real, **cualquier cambio en el funcional de regularización cambia también el λ que Morozov seleccionará**. Por tanto la comparación antes/después debe dejar que Morozov re-elija en ambos brazos, no fijar el λ del baseline. Comparar con λ congelado mediría otra cosa.

**Diseño propuesto.**
1. **No tocar el motor todavía.** Crear `scripts/validation/wz_separation_probe.py`: variante experimental del solver donde `Ws` se aplica como precondicionador diagonal *dentro* de LSQR/LSMR (no altera la solución del problema regularizado) y `W_z = (z+z₀)^(−β/2)` entra como bloque de smallness explícito `‖W_z·m‖²`.
2. Barrer β ∈ {0, 1, 1.5, 2, 3} × profundidad ∈ {150, 300, 600, 900} m × 5 semillas, con verdad analítica anti-inverse-crime.
3. Comparar contra el baseline de producción con Morozov.
4. **Decidir con el número, no con la teoría.**

**Cambios matemáticos.** Separar dos conceptos hoy fundidos: normalización algebraica (no debe cambiar la solución) y peso físico del modelo (debe cambiarla).

**Estrategia de pruebas.** Anti-inverse-crime obligatorio; ≥5 semillas; los 4 benchmarks externos como control de no-regresión.

**Criterios de aceptación.** (a) Tabla medida de error de profundidad con y sin separación, por régimen. (b) Decisión documentada: cablear o cerrar. (c) Si no mejora: `depth_beta` **se elimina de la firma** y los ~60 líneas de comentario se reescriben para describir lo que el código hace de verdad.

**Riesgos de regresión.** Altos si se cablea sin gate. Mitigación: F9 debe correr antes y después, y el default debe ser byte-idéntico hasta que el número lo justifique.

### ✅ EJECUTADA — 2026-08-14

*Iteración de backend únicamente. Antes de tocar nada se verificó que `depth_beta` **no** aparece en `terraquantum-web/` ni en ningún schema de **request**: sólo en `response_schema.py:97` como campo de salida, alimentado por **magnetometría**. Y que **ningún llamador de producción se lo pasaba nunca** al solver gravimétrico de grilla regular. Nada de esta fase cruza el contrato HTTP ni el frontend.*

#### 1. Primero la sonda; sólo después mirar el resultado

`scripts/validation/wz_separation_probe.py` reescribe el problema de `solve_inversion_lsqr` en **espacio físico**, separando los dos conceptos que producción tiene fundidos: `u`, el **peso de modelo** (entra en el funcional, *debe* mover la solución) y `P`, el **precondicionador de columna** (cambio de variable de *todo* el sistema, *no debe* moverla). Producción es el caso particular `u_j = ‖col_j(W_d·G)‖`, `P = diag(1/‖col_j‖)`.

| Control | Qué compara | Medido | |
|---|---|---:|---|
| **C1b** fidelidad | sonda(`u=‖col‖`,`P=colG`) vs `solve_inversion_lsqr`, mismo solver interno | **3,2e-14 t/m³** | PASA |
| **C1a** | la misma sonda vs producción con TRF | 1,76e-04 | PASA — *idéntico* a lo que se separan entre sí los dos solvers de producción |
| **C2** invariancia | `P=colG` vs `P=colA`, mismo funcional | **1,37e-09 t/m³** | PASA |
| **C3** perilla viva | β=0 vs β=2 **con la separación** | **49,8 % del pico** | PASA |

C1b a 3,2e-14 no es «se parece»: es la prueba de que la reescritura **es** el motor, y por tanto que todo lo que la sonda mida después habla del motor. C2 es la mitad algebraica de H-1 medida de frente — **el precondicionador no es física**. C3 es la otra mitad: en cuanto el peso deja de cancelarse, β mueve medio pico.

#### 2. La respuesta, medida

**576 puntos Morozov = 3.450 inversiones** (3,6 h-proceso), sobre esfera analítica (anti-inverse-crime), 8 semillas de ruido, **Morozov re-eligiendo λ en cada brazo** (como la fase exigía: comparar con λ congelado mediría otra cosa), en tres configuraciones.

**Error de profundidad del PICO — mediana sobre 8 semillas, en metros. Configuración de producción (L2 + padding):**

| brazo | 150 m | 300 m | 600 m | 900 m | **AGREGADO** |
|---|---:|---:|---:|---:|---:|
| **`prod`** (sensibilidad, β_eq 2,63) | 38 | **12** | **38** | 538 | **38** |
| `sep` β=0 (Tikhonov plano) | 88 | 238 | 538 | 838 | 388 |
| `sep` β=1 | 88 | 238 | 538 | 838 | 388 |
| `sep` β=1,5 | 88 | 175 | 288 | **88** | 131 |
| `sep` β=2 (*estándar industrial*) | 38 | 112 | 162 | 538 | 138 |
| `sep` β=3 | 38 | **12** | 88 | 538 | **62** |

**Y el agregado es el mismo en las tres configuraciones** — el padding y la norma no cambian el veredicto (ése era el control que se montó para poder afirmarlo):

| Configuración | `prod` | β=0 | β=1 | β=1,5 | β=2 | β=3 |
|---|---:|---:|---:|---:|---:|---:|
| L2 sin padding | **38** | 388 | 388 | 194 | 138 | 62 |
| L2 con padding *(= producción)* | **38** | 388 | 388 | 131 | 138 | 62 |
| compact con padding | **38** | 388 | 388 | 100 | 112 | 62 |

**DECISIÓN MEDIDA: CERRAR.** Ningún β fijo gana en los cuatro regímenes y las tres configuraciones a la vez (regla D1–D4, declarada en el script *antes* de mirar los números). La separación **resucita la perilla** —eso está medido, C3— pero la perilla **no tiene un valor que sirva para todos los casos**.

Tres lecturas que el número permite y la teoría no daba:

1. **Producción ya está cerca del óptimo de esa familia.** El brazo separado que mejor le compite es **β=3**, y es precisamente el más cercano al **β_eq = 2,63** que se midió para el peso efectivo de producción (§3.1 abajo). Dos análisis independientes —ajuste de la norma de columna y barrido de recuperación— apuntan al mismo exponente. Ningún β *mejora*: el peso que el kernel impone por accidente resulta ser un buen peso.
2. **La profundidad se compra y se paga.** β=1,5 rescata el régimen de 900 m (88 m frente a los 538 m de producción, 6×) y **arruina el de 300 m** (175 m frente a 12 m). Es el trade clásico, y aparece con **IQR de 238–312 m entre semillas** en ese mismo régimen profundo: incluso la «victoria» es inestable. Un peso que arregla 900 m y rompe 300 m es un **régimen, no un arreglo** — y el producto no sabe a priori en qué régimen está.
3. **El límite de profundidad no es un bug de implementación.** Es el null-space del dato, como `docs/05` §A′ ya sostenía. La diferencia es que ahora se puede decir **con autoridad**: se probó la reparación que la auditoría pedía probar, con el peso vivo y λ re-elegido, y el techo no se movió. Eso es exactamente el segundo resultado que §6.2 punto 4 anticipaba como valioso: *«cierra definitivamente la pregunta y permite vender el límite con autoridad»*.

*Efecto lateral honesto: los brazos separados sí **mejoran algo el error horizontal** agregado (β=1,5 da 9–10 m frente a los 14–17 m de producción). No basta para cambiar la decisión —el targeting horizontal ya es el observable sano del producto— pero queda registrado por si alguna vez se persigue esa décima.*

#### 3. Tres cosas que esta fase corrige de la propia auditoría

**(1) El peso efectivo NO tiene «forma distinta» al estándar industrial.** §6.2 punto 3 infería que `‖colⱼ‖` *«decae aproximadamente como 1/z², un peso mucho más agresivo y **de forma distinta** al estándar industrial»*. Medido (`--weight-shape`): ajusta a `(z+z₀)^(−β/2)` con **β = 2,63 y desviación máxima del 5,3 %** — una ley de potencia de **la misma familia** que Li & Oldenburg, con exponente 2,63 en vez de 2,0. Modestamente más agresiva, no de otra especie. Esto reencuadra H-1: **el problema no es que el peso esté mal, sino que no es ajustable y no está declarado** — lo fija el kernel, no una decisión.

**(2) `depth_beta` no era inerte del todo, y el residuo ya tiene nombre y número.** §9G.1 dejó el caveat explícito: *«si trunca por iteraciones, habría un efecto residual… No lo cuantifiqué.»* Cuantificado: mover β de 0 a 4 movía la solución **2,5e-04** (relativo L2) con TRF y **5,2e-06** con LSQR+GPCG. Que el número **cambie 48× al cambiar de solver** lo identifica como parada temprana y no como física: `Wz` seguía siendo un precondicionador por la derecha legítimo. *(Corolario: la afirmación de `docs/01_PLAN_MAESTRO.md` de que «beta=0 y beta=2 dan resultados byte-idénticos» es falsa en sentido estricto — son idénticos como física, no como bits.)*

**(3) Gravimetría también tiene DOS funcionales de regularización, no uno.** La auditoría documentó ese patrón como enfermedad de magnetometría (H-33, H-38) y para gravimetría cerró el cuadro con «❌ Nunca (H-1)». Medido (`wz_beta_liveness_gravimetry.py`):

| Solver | Dónde se calcula `Ws` | ¿`depth_beta` mueve la solución? |
|---|---|---:|
| `solve_inversion_lsqr` (:1728), malla regular | sobre el kernel **ya pesado** por `Wz` ⇒ se cancela | **2,5e-04** — residuo de parada temprana |
| `solve_inversion_treemesh` (:3633), malla Octree | sobre el kernel **sin pesar**; `w_reg` sólo en smallness/suavidad | **2,045** — **8.125× más** |

Y quién elige entre los dos **no es el usuario**: `should_auto_use_treemesh` (`services/octree_mesh_builder.py:117`) conmuta solo cuando la grilla pasa de **50.000 celdas** o el survey de **50 km**. Es decir: **la misma configuración nominal aplica un depth weighting o ninguno según el tamaño del levantamiento, y nada en la salida lo declara.** Es la patología de H-33 en el motor donde la auditoría la daba por descartada — **la separación que esta fase venía a probar ya existía escrita en el solver de al lado**. El arreglo (un único `build_model_weights()` que declare el funcional) es literalmente lo que pide la **Fase 7**, y esta medición le añade un motor más a su justificación.

*(Corolario menor: la nota `[D6]` de `audit_synthetic_test.py` —«el solver usa `depth_beta=2.0` y el módulo de focusing usa `_DEPTH_BETA=1.0`, inconsistencia»— queda sin objeto para el solver de grilla regular: no había β con el que ser inconsistente.)*

#### 4. Lo que cambió en el motor — criterio de aceptación (c)

Un archivo, una función: `exploration/gravimetry.py::solve_inversion_lsqr`.

* **`depth_beta` fuera de la firma**, y con él el cambio de variable muerto entero (`z0`, `true_depth`, `wz_inv_diag`, `Wz_inv`): con β cancelándose, `Wz_inv·Ws ≡ Ws`, así que la cadena de pesos se escribe **una vez** y dice la verdad. Los bounds pasan de `(d−base)/w_j · w_j‖col‖` a `(d−base)·‖col‖`, que es lo que siempre calcularon.
* **Los ~60 líneas de comentario reescritas.** El bloque «H-A0 Bug 1: W_z formal (Li & Oldenburg 1998)» describía un efecto que no ocurría. Ahora lleva la demostración de la cancelación en tres líneas, el número que la mide, el funcional que el código **sí** aplica (`φ = λ_eff²·Σⱼ(‖colⱼ(W_d·G)‖·mⱼ)²`), el β equivalente medido y el puntero al instrumento y al invariante. El log de cada corrida dejó de imprimir `depth_beta=2.0` y `smallness=W_z-formal(H-A0)`.
* **5 llamadores actualizados** (4 scripts de validación + `tests/audit_bushveld_phase3.py`), cada uno con la nota de por qué desapareció el argumento.

**Byte-identidad, medida en los 10 caminos que tocaban `Wz_inv`** (L2, compact/IRLS, padding, anclaje soft, anclaje hard, bounds litológicos, cross-gradient, `m_ref`, topografía no plana y todo junto):

| Solver interno | Peor diferencia relativa | Lectura |
|---|---:|---|
| TRF (`lsq_linear`) | 2,4e-04 | del orden del residuo de parada temprana ya medido |
| LSQR+GPCG | **1,4e-05**, con 6 de 10 casos a **1e-10…1e-14** | al converger mejor el solver, la diferencia se desploma |

Que caiga **17× sólo por cambiar de solver** es la firma de una identidad algebraica resuelta con tolerancia finita, no de un cambio de comportamiento. **No es bit-a-bit y no se afirma que lo sea.**

**Red que impide que vuelva:** `tests/test_fase4_depth_weighting.py` (3 tests, 8,6 s). *(a)* El peso de modelo efectivo **es** `‖colⱼ(W_d·G)‖` — se resuelve el mismo problema escrito a mano en espacio físico y se exige coincidencia a 1e-6, así que reintroducir cualquier peso en la cadena rompe la suite; *(b)* `depth_beta` no puede volver a la firma del solver donde no hace nada; *(c)* `solve_inversion_treemesh` **sigue** teniendo el peso vivo — sin este test, (b) invita a «limpiar por analogía» el solver donde el parámetro sí cambia la física.

**Gate F9 (regresión física) después del cambio: PASS 6/6** (98 min re-invirtiendo los datasets canónicos). No «pasa dentro de tolerancia»: **cada número es el mismo que antes**, que es la evidencia fuerte de que el refactor no movió la física.

| Caso | Post-cambio | Referencia histórica | Tolerancia |
|---|---:|---:|---|
| Esfera sintética (canario de forma) | **0,7259** | 0,7259 *(medido antes del cambio, misma sesión)* | r ≥ 0,70 |
| DO-27 (kimberlita) — error horizontal | **53,7 m** | 53,7 m | ≤ 70 m |
| Raglan Ni-Cu — pico interior | **212,1 m** | 212 m | ≤ 250 m |
| San Nicolás (VMS) — misfit | **1,51 %** | 1,51 % | ≤ 3 % |
| Laguna del Maule — χ² reducido | **0,9869** | 0,99 | ∈ [0,7 · 1,3] |
| Ambigüedad de profundidad | **2675 m** | 2675 m | LÍMITE documentado |

*Y un detalle que cierra el círculo: la nota del propio canario ya advertía que «con W_z apagado el veredicto no se mueve (r=0,7259 en los tres casos)». La Fase 4 explica por qué —no había W_z que apagar— y `tests/test_fase3_calibracion_absoluta.py` sigue siendo quien cubre las regresiones de escala.*

**Comandos de validación de esta fase**

```powershell
python scripts/validation/wz_separation_probe.py --controls      # C1/C2/C3
python scripts/validation/wz_separation_probe.py --weight-shape  # beta equivalente
python scripts/validation/wz_separation_probe.py --sweep --padding
python scripts/validation/wz_separation_verdict.py               # regla D1-D4
python scripts/validation/wz_beta_liveness_gravimetry.py         # los dos solvers
python -m pytest tests/test_fase4_depth_weighting.py -v          # la red
python scripts/validation/f9_gate_regression.py                  # regresión física
python scripts/ci/compile_check.py; python scripts/ci/ast_budgets.py; python scripts/ci/validation_inventory.py
```

*Aviso medido para quien repita esto: `tests/test_f8_perf_budgets.py::test_budget_inversion` es un presupuesto de **reloj de pared**. Con los tres barridos ocupando la máquina dio **122,9 s** contra un techo de 120 s; con la máquina libre, **63,75 s**. Antes de diagnosticar una regresión de rendimiento, repetir en limpio.*

**Un fallo propio, encontrado por la suite completa — y dos intentos hasta dar con la causa.** La suite entera dio **2.347 passed / 17 skipped / 1 failed**, y el fallo era **el test nuevo de esta fase**: pasaba aislado y fallaba en suite. No era el motor (F9 ya había re-invertido los cuatro datasets reales dando los mismos números): era el test, **orden-dependiente**.

*Primer diagnóstico, equivocado.* Medí que con `USE_PROJECTED_SOLVER=False` producción se salta la proyección GPCG mientras la referencia la aplica ⇒ **76 % de diferencia**, y como el test sólo fijaba una de las tres perillas del solver, lo di por explicado. Fijé las tres, comprobé que pasaba incluso arrancando con las tres invertidas… **y la suite completa volvió a fallar exactamente igual.** La comprobación que hice no era la que refutaba la hipótesis.

*Causa real, medida.* Aislado el reproductor mínimo (`test_fase2_arranque.py` + este test → falla en 3 s), los números señalan solos: el dato de entrada es idéntico, **la referencia es bit-idéntica (0,0e+00)** y **sólo producción se mueve (1,8e-03)**. El log del solver dice por qué: producción pasa de `LSQR+clip` a **`TRF/bounded`**. Y el motivo no es el valor de la perilla sino **la identidad del módulo**: `test_fase2_arranque.py` hace `sys.modules.pop("core.config")` + `importlib.import_module("core.config")`, que **construye un objeto de módulo NUEVO** y deja huérfana toda referencia tomada antes. El test hacía `import core.config as cfg` al importarse, así que **estaba parcheando un fantasma**: `id()` distinto, la perilla en `False` en el huérfano y en `True` en el vivo, y el motor —que resuelve el módulo por `sys.modules` en cada llamada— cogiendo TRF tan tranquilo. Corregido resolviendo el módulo **en el momento de usarlo**, no al importar.

**Dos lecciones que valen más que el arreglo.** (1) *Un invariante que depende de la configuración ambiente no es un invariante.* (2) *Recargar un módulo sustituyéndolo en `sys.modules` es una trampa silenciosa para cualquiera que lo tenga importado por nombre* — aquí sólo se manifestó como un test rojo, pero el mismo patrón podría dejar a un servicio leyendo configuración fantasma. Y queda anotada a propósito la ironía: la fase que persigue código que miente sobre sí mismo produjo un test que medía el solver creyendo medir el funcional, y un diagnóstico que sonaba bien y era falso hasta que lo refutó la medición.

#### 5. Lo que NO se hizo, y por qué

* **No se cableó nada.** El número no lo justifica, y la fase decía «el default debe ser byte-idéntico hasta que el número lo justifique».
* **No se tocó magnetometría.** H-33/H-38 dicen que allí `depth_beta` también es inerte en producción, pero **por otro mecanismo** (todos los bloques comparten `Wz_inv` cuando hay padding, y el padding es incondicional). Es un cambio de funcional, no de comentario, y su sitio es la **Fase 7**. La propia Fase 4 declaraba que «H-1 es exclusivo de gravimetría».
* **No se tocó `solve_inversion_treemesh`.** Ahí el peso está vivo y clavado en 2.0 por `getattr(params, "depth_beta", 2.0)` sobre un campo que **no existe** en el schema de request. Cambiar ese 2.0 es una decisión de física que exige su propio barrido: esta fase midió el peso equivalente de *otra* parametrización (`(z+z₀)^(−β/2)` sólo en smallness, frente a `(z+z₀)^(−β)` en smallness *y* suavidad) y **no lo transfiere**.
* **Los dos scripts del Punto 4 no se borraron.** `wz_smallness_liveness.py` y `wz_tradeoff.py` pasan `smallness_depth_beta=` a un solver que ya no lo acepta: **verificado, dan `TypeError`**. Borrarlos es trabajo de la Fase 6, ya cerrada. Se les puso cabecera de «INOPERANTE» con puntero al sucesor y su ficha en `GATES.json` dice lo mismo: un instrumento roto que la documentación cita como si midiera es la trampa de §9D.2, y ahora está marcada en vez de en limbo. — **✅ BORRADOS el 2026-08-14 en el cierre de la Fase 6.** Sus reportes JSON siguen en el directorio (la evidencia era el reporte, no el script), el código está íntegro en `cc2e7ab` y la cita de `docs/05` §Hallazgos endurecidos apunta ahora ahí.

---

---

## FASE 5 — Cerrar la superficie de configuración · **S** · 🟡 P2

*(antes «Fase I» — renumerada para que el rotulo sea el orden de ejecucion.)*

*(Fase nueva, derivada de H-11. Se solapa con la Fase 3 y puede fusionarse con ella.)*

**Objetivo.** Que ninguna variable de entorno documentada pueda estar rota sin que la CI lo diga.

**Trabajo.** Test parametrizado sobre las 44 variables: para cada una, arrancar el camino que controla y verificar que importa y responde. Las 8 del solver, además, con una inversión mínima real. Resolver explícitamente `TQ_AUTH_ENABLED` (documentado como "rompería la UI"): o se arregla, o se elimina, o se marca como no soportado en la documentación de despliegue.

**Criterios de aceptación.** 0 variables sin ejercitar. La CI falla si se añade una nueva sin test.

**Riesgo.** Muy bajo. **Caza H-2 automáticamente y previene su reaparición.**

### ✅ EJECUTADA — 2026-08-15

*Iteración de backend únicamente (regla de oro del repo). El frontend se **midió** —leerlo no es tocarlo— y lo que hay que arreglar allí queda escrito abajo con nombre y número.*

**Gate: 154 tests nuevos en `tests/test_fase5_superficie_config.py`.** `compileall` OK. La fase cabe en el paso barato de la CI (guardas de arquitectura), no en el de la hora.

**Corrida completa de la suite: `2.459 passed, 1 failed`** en 2 h 13 min, y el único fallo restante (`test_fase7_wiring`) es **anterior a esta fase y está declarado** — ver §8, donde también se cuenta lo que la suite completa encontró y el archivo de la fase no.

#### 1. El inventario: no eran 44 sino 42, y la diferencia importa

El AST sobre **todo** el backend —incluyendo `os.environ[...]` y `os.environ.get(...)`, que un `grep getenv` no ve— confirma las **44** de §9B.3. De ellas, dos no son superficie del producto y se declaran como tales en vez de inflar el número: `ENABLE_FOCUSING` (borrada, ver abajo) y `ROI_CSV`, que vive en `terraquantum-backend/tmp/`, **directorio en `.gitignore`**. Incluir `tmp/` habría hecho que el inventario diera un número distinto en la CI que en la máquina de Martín, y *un invariante que depende del entorno no es un invariante* (lección de la Fase 4, aplicada). Quedan **42**: 29 que lee código de producción y 13 que sólo leen tests y scripts de gate.

La Fase 3 inventariaba **22** (sólo `core/config.py`). Las otras veinte viven en `api/chat_api.py`, `services/run_queue_service.py`, `services/gee_client.py`, `services/joint_inversion.py`, `services/gemini_agent.py` y en los propios scripts F7/F8.

**El registro declara para cada variable su tipo, su ámbito, su dueño y —lo que importa— su NIVEL de ejercicio**, en una escala honesta: `inversion` (se mide con una inversión real) > `llamada` > `arranque` > `externo` (el ejercicio vive en otro archivo, que se nombra y se comprueba que sigue mencionándola) > `sitio` (sólo se verifica el sitio de lectura). **Una sola variable de producción se queda en `sitio`** —`JOINT_ENABLE_GEMINI`, que se lee a mitad de una inversión conjunta de minutos— y para ello hay que inscribirla en una lista aparte con el motivo escrito. Que cueste es el punto: H-11 nació de que nadie tuvo que justificar nada.

#### 2. La sonda de la Fase 3 comprobaba que el módulo CARGA, no que la variable LLEGUE

Es la corrección metodológica de la fase. `test_config_reloads_with_each_flag` recargaba `core.config` con la variable puesta y comprobaba que existieran `host` y `port`: **eso pasa igual si la variable se ignora por completo**. Ahora cada una declara *dónde se observa su efecto* (`c.BACKEND_HOST`, `c.TQ_TIER_LIMITS['free']['max_voxels']`, `_CACHE_TTL_SECONDS`, `_MAX_WORKERS`…) y el test lee ese valor. Un módulo que ignore la perilla ya no pasa.

`test_fase3_config_matrix.py` **se borra**: sus cuatro comprobaciones están aquí, cada una más fuerte. La propia auditoría preveía la fusión, y mantener dos registros de las mismas variables es exactamente la enfermedad que esta fase cura.

#### 3. Cinco huecos MEDIDOS, y ninguno estaba en la lista de la auditoría

| # | Qué | Cómo se midió | Por qué importa |
|---|---|---|---|
| 1 | **`ENABLE_FOCUSING` era una perilla inerte.** `main.py` la leía del entorno, la guardaba en `_ENABLE_FOCUSING` y nadie la miraba jamás | sus 2 únicas apariciones en todo el repo eran su comentario y su asignación | Mismo pecado que `USE_SPARSE_DIRECT` (H-2) y las dos de wavelet (H-13), ya borradas. **BORRADA**, con su lápida |
| 2 | **El rollback documentado no funcionaba con `0`, `no` ni `off`.** `USE_BOUNDED_SOLVER=0` dejaba el solver bounded **activo** | inversión real de 384 celdas: modelo byte a byte **idéntico al default** | El comentario de esa misma línea documenta `=false` como rollback. Quien lo intentara con la forma que escribe todo el mundo no obtenía rollback **ni aviso** |
| 3 | **`TQ_AUTH_ENABLED=` (vacío) ENCENDÍA la autenticación** | arranque completo: `POST /geophysics/invert` pasó de 404 a **401** | El cargador de `.env.local` parte por el primer `=`, así que la línea `TQ_AUTH_ENABLED=` deja cadena vacía. Se rompe el camino dorado escribiendo una variable que se lee como apagada |
| 4 | **`bounded_solver_active` decía lo que se PIDIÓ, no lo que PASÓ** | 8.712 celdas activas: el solver despachó `LSQR+clip` y el campo afirmaba `true` | Ver §4 abajo — es H-37 otra vez |
| 5 | **Tres lecturas numéricas fuera de `core/config.py` morían sin nombrar la variable** | `int(os.getenv(...))` crudo en `chat_api` y en `run_queue_service` ×2 | La Fase 3 arregló esto **dentro** de `config.py` y la costumbre no cruzó el archivo. La peor, `TQ_TEST_SLOW_BEFORE_SOLVE_S`, se lee **dentro del worker**: mataba la corrida a mitad |

**El arreglo de fondo de los huecos 2 y 3 es uno solo: había DOS vocabularios booleanos y los dos mentían.** Las perillas con default ON se leían `!= "false"`; las de default OFF, `== "true"`. Un usuario no tiene por qué saber cuál le tocó. Ahora hay un `_env_bool` único —`1 true t yes y on si` / `0 false f no n off`, vacío = el default declarado, **y un valor ininteligible detiene el arranque nombrando la variable**, igual que ya hacía `_env_int`. Adivinar en silencio es cómo un flag de seguridad acaba encendido sin que nadie lo pidiera.

#### 4. Las perillas del solver, medidas con una inversión real — lo que la Fase 3 dijo que no podía ver

Malla de 8×6×8 = **384 celdas activas**, 49 estaciones, cuerpo enterrado, 1 % de ruido. Cada configuración corre en su propio subproceso **con la variable en el entorno**, de modo que lo ejercitado es la cadena entera: entorno → `core.config` → despacho. El truco que lo hace barato: 384 celdas están por debajo del umbral de TRF (8.000) y por encima de un `LSMR_THRESHOLD_N_ACTIVE` que se puede bajar a 100 — **los tres caminos del solver se alcanzan en la misma malla diminuta**.

| Perilla | ¿Viva? | Lo medido |
|---|---|---|
| `USE_BOUNDED_SOLVER` | **Sí** | `TRF/bounded` → `LSQR+clip`, y el modelo cambia |
| `USE_PROJECTED_SOLVER` | **Sí, y caro** | apagarla lleva el **χ² de 0,244 a 22,7 — 93×**. El comentario histórico decía «el clip degradaba el misfit ~35 %»; el número real en este caso es de otro orden. No es una preferencia de solver: es ajustar el dato o no ajustarlo |
| `USE_LSMR_LARGE` | **Sí** | con el umbral bajado, el despacho pasa a LSMR y vuelve a LSQR al apagarla |
| `LSMR_THRESHOLD_N_ACTIVE` | **Sí** | mueve la frontera LSQR/LSMR |

> **Matiz honesto, medido y escrito en el test.** LSMR y LSQR producen aquí el **mismo modelo** (coinciden a nueve decimales; cond(A)≈1e2, un sistema bien condicionado donde ambos convergen al mismo sitio). Eso **no** es inertidad —el despacho cambia y se comprueba— sino acuerdo, que es lo que uno querría. La perilla existe para mallas de 50k+ mal condicionadas, y **ese régimen no cabe en un test de segundos: se dice en vez de fingir que se prueba.**

#### 5. El hueco nº 4 es H-37 otra vez, y en el régimen NORMAL del producto

`bounded_solver_active` se calculaba en `geophysics_service` con `os.getenv("USE_BOUNDED_SOLVER")` — o sea, lo que se **pidió**. Pero el solver sólo despacha TRF **por debajo de 8.000 celdas activas**, y el producto declara mallas de 30k-100k vóxeles. Es decir: **el campo no fallaba en un caso de borde, fallaba casi siempre.** Y `validation/runner.py` lo lee para caracterizar cada corrida — era evidencia de validación contaminada.

Ahora sale de `solver_meta`, que es quien sabe qué se ejecutó, y el reporte gana `solver_path` (`TRF/bounded` · `LSMR` · `LSQR+clip`), `bounded_solver_requested` y `projected_solver_used`: **lo que se pidió y lo que pasó, por separado**. Dos tests lo defienden: uno que invierte 8.712 celdas y mide el desacuerdo, y una guarda estática por AST —el error original era de UNA línea y alguien puede rehacerlo sin querer.

#### 6. `TQ_AUTH_ENABLED`, resuelta como pedía la fase — y la doc estaba mal

La fase exigía *o se arregla, o se elimina, o se marca como no soportado*. Se marca, **con el número corregido**: `docs/03` decía *«el frontend nunca envía `X-TQ-API-Key`»* y es falso por la mitad. MEDIDO: de los **43** proxies de Next.js, **17 SÍ la reenvían** (desde `process.env.TQ_API_KEY`) y **26 no**, entre ellos `geophysics-invert`.

**La rotura no es total, es asimétrica**: importar y exportar funcionan, invertir devuelve 401. Es peor de diagnosticar que una caída limpia — el usuario ve una app que a ratos funciona. Y hay un segundo piso: el orquestador de escritorio (`src-tauri/src/lib.rs`) no fija `TQ_AUTH_ENABLED` **ni** `TQ_API_KEY`, así que ni los 17 tendrían clave que enviar.

Veredicto declarado en `docs/04` §9.3: **perilla de despliegue SERVIDOR/Docker, no soportada con la UI web**, dicha en voz alta en cada arranque en los dos sentidos (antes sólo avisaba cuando estaba apagada — el aviso que faltaba era justo el del caso que rompe). Y la puerta de atrás se cerró: el vacío ya no la enciende.

#### 7. La documentación de despliegue deja de poder quedarse atrás

`docs/04_EMPAQUE_LOCAL_FIRST.md` §9 documenta las **29 variables de producción** en cinco tablas (arranque/red · motor · licencia y auth · servicios externos · observabilidad), y **un test falla si el producto lee una que la doc no menciona**. Es la deriva que produjo H-11 —la superficie creció durante catorce fases sin que nadie llevara la lista— cerrada por construcción y no por disciplina.

#### 8. Lo que la suite completa dijo después, y por qué vale la pena contarlo

El archivo de la fase estaba verde y la regresión dirigida a los ocho módulos tocados también (70 tests). **La suite completa —2 h 13 min, 2.459 passed— encontró igualmente dos cosas**, y las dos son de la clase que sólo aparece corriéndolo todo:

1. **`test_gee_credentials_path_llega_a_init_gee` pasaba aislado y fallaba en suite.** Asertaba `is_available() is False` después de apuntar a un archivo inexistente. Pero `_gee_available` es un **global de módulo** y `init_gee()` retorna sin tocarlo cuando la ruta no existe: si otro test lo dejó en `True`, la aserción cae. Es literalmente la trampa que la Fase 4 dejó documentada, cometida otra vez. Arreglado fijándolo a `False` con `monkeypatch` antes de llamar — así la aserción **dice algo** (que esta llamada no lo encendió) en vez de depender del orden.
2. **El presupuesto AST de la Fase 3 se puso rojo, y tenía razón.** `core.loc` pasó de 1.774 a 1.881 (+107): los lectores tipados y sus docstrings con lo medido. Es crecimiento deliberado y de **infraestructura**, que es justo para lo que existe el Core — pero el techo se sube a mano y por escrito, que es el ritual que ese gate impone.

   **Y el gate ganó su sueldo por un motivo mejor.** Al correr `--update` se vio que también subiría `exploration.cc_max` de **143 a 144**: la primera versión del arreglo del §5 metía un `if solver_meta is not None` dentro de `solve_inversion_lsqr` — la función de 1.039 líneas y CC=143 que la **Fase 8 tiene que partir**. Aceptar ese techo habría sido pagar la corrección de un reporte con complejidad en la espina dorsal. Se reescribió sin rama: el despacho se anota en locales y se publica en el bloque `if solver_meta is not None` **que ya existía** al final. `cc_max` vuelve a 143, y el modelo sale **byte a byte idéntico** (mismo sha, mismo χ² y misma norma L2 a todos sus dígitos) — comprobado, porque un cambio de contabilidad que mueva un número no sería un cambio de contabilidad.

**El cuarto fallo NO es de esta fase**: `test_fase7_wiring::test_e2e_enabled_changes_model_and_reports` da `max_diff=9,10e-05` contra un umbral de `1e-4` —un 9 % por debajo— sobre `implicit_geology`, y viene declarado como deber pendiente desde el cierre de la Fase 6, que ya lo midió A/B. La comprobación de inercia numérica de arriba descarta que esta fase lo haya causado.

#### 9. Lo que NO se hizo, y por qué

* **No se tocó el frontend.** Reenviar la cabecera en los 26 proxies es mecánico y de bajo riesgo, pero es una iteración de frontend (regla de oro), y **por sí sola no arregla nada**: sin que el orquestador acuñe una clave y la pase a los dos procesos, los 43 reenviarían una cabecera vacía. Es trabajo de producto, escrito con su alcance en `docs/04` §9.3 en vez de quedar como rumor en un comentario.
* **No se cablearon las perillas que faltan.** `JOINT_ENABLE_GEMINI` se queda en el nivel más débil de ejercicio, declarada y con el motivo escrito.
* **No se validó el régimen para el que existe LSMR** (50k+ celdas mal condicionadas): no cabe en un test de segundos y se dice en vez de simularlo.
* **`ROI_CSV` no se tocó** — vive en `tmp/`, que `CLAUDE.md` prohíbe tocar y `.gitignore` excluye.
* **La deuda que esta fase deja anotada, y es la única nueva**: `TQ_TEST_SLOW_BEFORE_SOLVE_S` es un gancho de prueba que lee **código de producción**. Es inocuo sin la variable, ahora está declarado y documentado como lo que es, pero un gancho de test en el camino del usuario es deuda, no diseño.

---

---

## FASE 6 — Limpieza verificada · **S** · 🟡 P2

*(antes «Fase D» — renumerada para que el rotulo sea el orden de ejecucion.)*

**Objetivo.** Borrar lo muerto con evidencia, como se hizo en F1 pero completando lo que aquella pasada no alcanzó.

**Trabajo (cada ítem con su evidencia medida en esta auditoría):**

| Qué | Evidencia | Ref. |
|---|---|---|
| `reactiveUpdateGraph.ts` | 0 consumidores | H-6 |
| Cadena `InstancedSegmentsLayer`+`segmentLOD`+`webgpuCull` | sin importadores externos. **Decidir explícitamente**: borrar o cablear, no dejar en limbo | H-6 |
| `engine-physics.ts` | física de demo en TS, sin importadores | H-6 |
| Bloque `USE_SPARSE_DIRECT` + su flag | símbolo inexistente ⇒ `NameError` | H-2 |
| `core/storage.py` | huérfano total; nube rechazada por estrategia | H-12 |
| `distributed`, `shapely` de `requirements.txt` | 0 imports; peso del instalador | H-14 |
| `credenciales_gee.json.REVOKED_*` fuera del árbol | clave privada real committeada | H-7 |
| Los 16 símbolos públicos sin referencia | revisar uno a uno: borrar o cablear | H-13 |
| **Mover `block_model_store`, `geo_utils` → `services/` y `gee_client` junto a `satellite_service`** | 41% del Core es dominio; **no hay dependencias ascendentes que romper**, es mover archivos y actualizar imports | H-35 |

**Criterios de aceptación.** Cada borrado con su grep de cero consumidores en el mensaje de commit. `tsc --noEmit` y `eslint` limpios. Suite verde. Tamaño del instalador medido antes y después.

**Riesgo.** Muy bajo. **[OPINIÓN] Es la fase con mejor relación valor/riesgo de todo el plan** y puede hacerse en paralelo a cualquier otra.

### ✅ EJECUTADA — 2026-08-09

*Dos iteraciones separadas (backend y frontend, regla de oro del repo).*

**Contabilidad honesta de las líneas** (separando lo borrado de lo movido, que no es lo mismo):

| | Líneas |
|---|---:|
| **Código muerto BORRADO** — 9 archivos que desaparecen (1.644) + 7 símbolos recortados de archivos que sobreviven (476) | **≈ 2.120** |
| Código **MOVIDO** fuera de `core/` (sigue existiendo, en `services/`) | 1.306 |
| Añadido: test anti-regresión de la fase | +293 |
| Añadido: comentarios que explican cada borrado en su sitio | +169 |

**Gate cumplido:** backend `compileall` OK · **2.308 tests colectan** sin error de import · **321 passed** en los 28 archivos que importan los módulos movidos · **57 passed** en los módulos podados · **26 tests nuevos** de la propia fase. Frontend `tsc --noEmit` **0** · `eslint` de fuentes **0 errores** · `next build` **OK**.

| Hallazgo | Qué se hizo | Evidencia de cero consumidores |
|---|---|---|
| **H-2** | Borrado el bloque `USE_SPARSE_DIRECT` (`gravimetry.py`) **y su flag**. `elif _use_lsmr` pasó a `if`. | El símbolo `solve_sparse_normal_equations` no existe en el repo (grep global); la flag sólo la leía ese bloque |
| **H-12** | Borrado `core/storage.py` (168 LOC). | 0 importadores; la única mención era un **comentario** en `config.py:127`, también retirado |
| **H-13** | Borrados 7 símbolos (**−557 LOC**): `solve_inversion_lsmr_wavelet`, `remove_regional_scale`, `build_gradient_operators_from_mesh`, `export_core_to_gslib` + `export_block_model_to_gslib`, `configure_logging`, `resolve_mine_design_block_model_reference`. | Cada uno: 1 sola aparición en todo el repo = su propia definición |
| **H-14** | `shapely` y `distributed` fuera de `requirements.txt`. | `shapely`: única aparición en el repo = la propia línea del requirements. `distributed`: **ni siquiera está instalada** en la máquina donde el backend corre y sus tests pasan |
| **H-35** | `block_model_store`, `geo_utils` y `gee_client` movidos a `services/` (56 archivos de imports reescritos). **`core/` pasa de 3.176 a 1.759 LOC (−45%) y su fracción de dominio de 41% a 0%.** | `exploration/` (la física) **no importaba ninguno de los tres**: el motor no se toca |
| **H-6 / H-31** | Frontend: borrados 8 archivos (**−1.492 LOC**) — `reactiveUpdateGraph`, la cadena `InstancedSegmentsLayer`+`segmentLOD`+`webgpuCull`, `engine-physics`, `geophysicsModel`, `ColorPipeline` y `geophysicsSurvey`. | 0 importadores reales; ver decisión de la cadena abajo |
| **H-7** | **NO ejecutado a propósito** — ver abajo. | — |

**Tres cosas que la auditoría no había medido bien, y ahora sí:**

1. **Quitar `shapely` y `distributed` NO reduce el instalador ni un byte.** La auditoría infería una "reducción gratuita de tamaño" por ser dependencias pesadas. Medido en el TOC de PyInstaller del build real: `shapely` **0 entradas**, `distributed` **0**, `pywt` **0** — frente a `scipy` 3.034 y `dask` 172. El análisis estático ya las excluía por inalcanzables. El instalador sigue en **321,5 MB** y el sidecar en **198,8 MB**. La ganancia real es otra: el manifiesto deja de mentir sobre lo que el producto necesita.
2. **Mover `block_model_store` habría creado la arista `core/ → services/`** que la Fase 3 va a prohibir. `core/utils.py` importaba `clean_trace_id` **hacia arriba**, desde el almacén de modelos de bloques. La auditoría decía "no hay dependencias ascendentes que romper" — cierto para las que existían, pero el movimiento **fabricaba una**. Se resolvió antes de mover: sanear un identificador para usarlo como nombre de carpeta es infraestructura, así que `clean_trace_id` bajó a `core/utils.py` y el almacén lo reexporta (sus importadores no cambian).
3. **Las dos perillas de wavelet eran el mismo pecado que H-2.** `USE_WAVELET_COMPRESSION` y `WAVELET_THRESHOLD_N_ACTIVE` prometían activar la compresión del Jacobiano y **ningún código las leía**: su único consumidor posible era `solve_inversion_lsmr_wavelet`, que nunca se cableó. Se borraron con él. Los building blocks siguen vivos y con tests en `exploration/jacobian_wavelet.py`. Tras la poda, **cero constantes de `core/config.py` quedan sin lector** (medido). *(**Corregido el 2026-08-14**: dejar los building blocks «vivos con tests» fue dejar el limbo a medias — sin llamador, esos tests eran sus únicos importadores. El módulo y la dependencia `PyWavelets` se borraron al cerrar la fase; ver `### ✅ CERRADA DEL TODO`.)*

**La decisión que la fase pedía tomar explícitamente ("borrar o cablear, no dejar en limbo"): BORRAR la cadena de sondajes.** El ADR del render declaraba que los slices 3 y 4 no se montaban porque las coordenadas de sondaje no tenían transform al frame re-centrado. Ese problema **ya se resolvió por otro camino**: `GET /borehole/view` entrega hoy los intervalos en coordenadas del visor, y quien los consume es `BoreholeLayer.tsx`, **montada y viva** en `Scene3D.tsx`. Es decir: los sondajes ya se dibujan, y `InstancedSegmentsLayer` era un **segundo motor superado por el que se entrega**. Además su LOD y su culling GPU están dimensionados para 1M+ segmentos, cuando el producto declara 30k–100k vóxeles — la propia auditoría llama sobreingeniería a eso. Cablearlo habría significado sustituir una capa que funciona por una cuyo WGSL **nunca corrió en una GPU real**. Queda registrado en `terraquantum-web/docs/ADR-fase6-render.md`, no borrado en silencio.

**Lo que NO se hizo, y por qué.**
- **H-7 (la clave privada revocada) queda para Martín.** `CLAUDE.md` prohíbe explícitamente tocar credenciales, y el archivo lo es. Lo que sí se hizo es **cerrar la causa raíz**: `.gitignore` exigía que el nombre *terminara* en `.json`, así que `*gee*.json` **no cubría** `credenciales_gee.json.REVOKED_2026-06-03` — **el renombrado que pretendía neutralizar el archivo es justo lo que lo dejó fuera del ignore y permitió committearlo**. Ahora se cubre cualquier sufijo. El borrado del árbol es un comando de dos líneas y la purga de la historia sólo hace falta si el repo sale de la máquina.
  - **✅ HECHO por Martín** — commit `7b9cd07` («sacar del árbol la credencial GEE revocada y tapar el patrón»). Verificado el 2026-08-14: el archivo no está en el índice (`git ls-files` no lo lista) ni en el árbol de trabajo. **H-7 cerrado.** Queda vivo sólo el matiz declarado arriba: la purga de la HISTORIA (`filter-repo`/BFG) sigue pendiente y sólo hace falta si el repositorio sale de esta máquina.
- **`PUBLIC_DIR` y `GEMINI_MODEL_NAME` se revisaron y NO son código muerto**: no tienen lectores externos, pero sí uso interno dentro de `config.py`. Se dejan.

**Red que impide que vuelva:** `tests/test_fase6_limpieza_verificada.py` (26 tests). Convierte cada borrado en un invariante ejecutable: los símbolos y flags borrados no pueden reaparecer, las deps muertas no pueden volver a `requirements.txt` ni como import, **`core/` tiene lista blanca de módulos** (uno nuevo sin declarar rompe la suite), **`core/` no puede importar hacia arriba** (anticipo del test de capas de la Fase 3), y ninguna constante de `config.py` puede quedarse sin lector. Incluye contraprueba de que la poda no se llevó nada vivo.

### ✅ CERRADA DEL TODO — 2026-08-14

*La pasada del 08-09 hizo el trabajo grande; este cierre responde a una pregunta que aquella no se hizo: **¿cuántos de los 16 símbolos de H-13 se revisaron de verdad «uno a uno»?***

**La respuesta era 6.** §9B.5 midió 16 huérfanos pero sólo tabuló los *«destacables por su significado»*; la ejecución resolvió esos 6 (7 símbolos, porque `export_*_to_gslib` eran dos) y **los otros diez nunca se enumeraron en ningún sitio**. No es que se decidiera dejarlos: es que salieron del radar en cuanto la lista dejó de estar escrita. Al volver a medir con un cruce de referencias AST sobre código + tests + scripts —un símbolo está muerto si su única aparición en TODO el repositorio es su propia definición— aparecieron **11**, y ninguno estaba en la tabla original.

**Contabilidad honesta de las líneas** (misma regla que la primera pasada: no se suma lo que sólo cambia de sitio, y los comentarios que explican un borrado no cuentan como borrado):

| | Líneas |
|---|---:|
| **Código muerto BORRADO** — 4 archivos que desaparecen (564: `jacobian_wavelet` 203, los dos scripts del Punto 4 306, `PostFX.tsx` 55) + símbolos recortados de archivos que sobreviven (382) + tests de lo borrado (95) | **≈ 1.041** |
| Añadido: la lápida de cada borrado, en su sitio | +99 |
| Añadido: red anti-regresión (de 26 a 48 tests) | +175 |

| Símbolo | Dónde | Decisión y por qué |
|---|---|---|
| `INVERSIONS_TOTAL`, `INVERSION_DURATION`, `ACTIVE_INVERSIONS` | `core/metrics.py` | **BORRAR.** Definidas y jamás incrementadas: el docstring del módulo enseñaba a instrumentar una llamada que nunca se escribió. Con el Gauge el daño era **peor que código muerto**: un Gauge sin etiquetas sí se emite, así que `GET /metrics` publicaba `terraquantum_active_inversions 0.0` **también mientras una inversión corría** — una lectura falsa, no una ausencia. No hay Prometheus ni Grafana en ninguna parte del repo. La instrumentación HTTP, que sí mide, se queda |
| `upward_continue_gravity_fft` | `exploration/preprocessing.py` | **BORRAR.** 151 líneas de continuación hacia arriba por FFT, cero llamadores y **cero tests**. Mismo cadáver y misma familia que `remove_regional_scale` (borrado en la primera pasada): ambos servían el pipeline regional de Bushveld, que este proyecto midió y descartó. Física correcta sin un solo test en el módulo de preprocesamiento es una invitación a cablear física no validada al camino crítico |
| `calculate_optimal_block_size` + `auto_compute_grid_params` | `services/gravity_import_service.py` | **BORRAR (153 LOC).** No hubo que investigar el motivo: su propio docstring lo declaraba — *«Legacy A1.0 grid helper. A1.3 flow uses `services.grid_calculator_service.compute_auto_grid`»*. El sucesor está vivo, se llama desde ese mismo archivo y tiene su suite. Dos calculadoras de grilla en un módulo, una muerta, es cómo se arregla un bug de mallado en la que nadie ejecuta |
| `normalize_unit` | `services/gravity_import_service.py` | **BORRAR.** Era `return unit.strip()`. Por el nombre parece **la** función de normalización de unidades; la de verdad es `canonicalize_unit`, que traduce los alias ("milligal", "gamma"…). Cablearla por error habría metido un CSV en milligal como si fuera m/s² — corrupción silenciosa, justo lo que el blindaje de ingesta existe para impedir |
| `ALLOWED_MAGNETIC_UNITS` | `services/gravity_import_service.py` | **BORRAR.** Copia literal y muerta de las claves magnéticas del mapa vivo de `canonicalize_unit`. **Deuda registrada al borrar:** el pipeline magnético canonicaliza la unidad pero no **rechaza** una desconocida; validar eso cambia qué CSVs se aceptan — comportamiento de ingesta, no limpieza |
| `compute_free_air_correction_simple` | `services/gravity_corrections_service.py` | **BORRAR.** FAC de coeficiente fijo 0.3086; el pipeline usa siempre la dependiente de latitud, que es estrictamente mejor y cuesta lo mismo. Mantener las dos era ofrecer una elección cuya única diferencia posible es un resultado peor |
| `normalize_array` | `services/geophysics_service.py` | **BORRAR.** Min-max a [0,1] sin un solo llamador |
| `queue_snapshot` | `services/run_queue_service.py` | **BORRAR, dejando dicho el hueco.** Su docstring decía «diagnóstico/UI» y no hay endpoint que la exponga ni pantalla que la pinte: **la cola no es observable desde fuera del proceso**. Dejarla puesta inducía la conclusión falsa de que basta con cablearla — si la Fase 9 quiere mostrar la cola, tiene que escribir el endpoint |
| `MAGNETIC_SUSCEPTIBILITY_PRESETS` | `core/config.py` | **BORRAR** (lo dejó anotado la Fase 3 y es trabajo de ésta). Cero consumidores de producción: su único lector era un test que comprobaba la tabla **contra sí misma** — no podía fallar por una regresión del producto. Y era **dominio dentro del Core**: la primera pasada declaró «`core/` al 0% de dominio» con esta tabla petrofísica todavía dentro. Ahora ese 0% es cierto |

**Dos limbos que la propia auditoría había asignado a esta fase y seguían abiertos:**

1. **`exploration/jacobian_wavelet.py` — BORRADO, con la dependencia `PyWavelets`.** Es el ejemplo más limpio de por qué la regla es *«borrar o cablear, no dejar en limbo»*. La primera pasada borró el llamador (`solve_inversion_lsmr_wavelet`) y las dos perillas de config, y dejó los building blocks *«vivos y con tests»*. Pero sin llamador **esos tests eran sus únicos importadores**, y cuando la Fase 3 los ejecutó por primera vez en un runner con PyWavelets instalado midió que el algoritmo **no cumple su propio criterio §10.6.1** (98,2% retenido exigiendo <15%; 0,615% de error forward exigiendo <0,5%), y los dejó en `xfail(strict=True)`: honesto, pero una promesa incumplida en mantenimiento indefinido. Cablearlo no era opción para una fase de limpieza —falla su criterio, así que exige rehacer el algoritmo, y eso es física—, de modo que se borra el módulo, sus tres tests y la dependencia, que existía **sólo** para él (`pywt` no tenía ningún otro importador en el repo). Recuperable íntegro en `git log`.
2. **`wz_smallness_liveness.py` y `wz_tradeoff.py` — BORRADOS.** Desde el revert del W_z-fix pasaban `smallness_depth_beta=` a un solver que ya no acepta ese argumento: ejecutarlos daba `TypeError`. La Fase 4 les puso cabecera de «INOPERANTE» y dejó el borrado aquí. **Su evidencia no se tocó**: `wz_smallness_liveness_report.json` y `wz_tradeoff_report.json` siguen en el mismo directorio, el código está íntegro en `cc2e7ab`, y la cita de `docs/05` ahora apunta al reporte y al commit en vez de a un script que no existe. Sucesor vivo: `wz_separation_probe.py`.

**Lo que NO se borró, y esta vez con la distinción dicha en voz alta.** Quedan tres símbolos sin referencia — `GeophysicsInvertResponse`, `GeorefSummary`, `BlockModelArrowMetadata` — y **no son código muerto: son contratos escritos que nadie enforza.** `GeophysicsInvertResponse` describe la respuesta de la inversión mientras el endpoint declara otra; `GeorefSummary` lo replica a mano el frontend en `frontendApi.ts` (H-16); `BlockModelArrowMetadata` documenta cabeceras `X-TQ-*` que se escriben a mano. Borrarlos tiraría la única descripción escrita de esas formas, y arreglarlos —cablear `response_model=` o generar los tipos desde OpenAPI— **cambia la serialización en runtime, o sea comportamiento**: es la Fase 10. Van declarados uno a uno en `HUERFANOS_TOLERADOS`, con motivo y fase dueña.

**La red, ampliada de 26 a 48 tests.** Lo importante no son los 22 tests nuevos que nombran cada borrado, sino **el que mide**: `test_h13_ningun_simbolo_publico_nuevo_se_queda_sin_consumidor` recorre todos los símbolos públicos de producción y falla si alguno tiene como única aparición su propia definición. Los tests que nombran defienden borrados concretos y no habrían impedido nada de lo que este cierre encontró — porque el problema no fue que volvieran los muertos, sino que **nadie volvió a medir**. Mira el AST y no el texto a propósito: si contara comentarios, la lápida que explica un borrado mantendría vivo al muerto. Las salidas legítimas están escritas en el mensaje de fallo: cablearlo con su test, borrarlo con su lápida, o declararlo con su motivo y su fase.

**Hallazgo NUEVO del cierre, en el frontend: cuatro superficies de UI construidas y nunca montadas — y dos de ellas dejan varada una función del backend.** Los 8 borrados de la primera pasada siguen en pie (verificado sobre el índice de git). Pero al medir los 129 módulos TS/TSX versionados con el mismo criterio —¿alguien lo importa?— aparecen 4 sin ningún importador (el quinto candidato, `voxelBufferBuilder.worker.ts`, es un **falso positivo**: `Scene3D.tsx:622` lo carga con `new URL(...)`, que no es un import).

| Módulo | Qué mide el rastreo | Consecuencia |
|---|---|---|
| `viewport/SliceControls.tsx` | **Nadie más escribe el estado del corte.** `SectionPaintLayer` sí está montada en `Scene3D` y el endpoint `/api/section` existe | El plano de corte tipo Leapfrog **es inalcanzable para el usuario**: la capa que pinta la sección está viva y no hay nada que la encienda |
| `viewport/MultiPhysicsControls.tsx` | `setViewMode` sólo se llama desde aquí y desde `packageInversion.ts:288`, que lo fija **automáticamente** según la física | El usuario **no puede cambiar de vista a mano** (densidad / susceptibilidad / incertidumbre): la ve según lo que decidió la corrida |
| `MultimodalComboPanel.tsx` | Único consumidor de `/api/multimodal/plan` fuera del proxy y del cliente HTTP | La función multimodal de la Fase 21 tiene **UI escrita y no montada**: es H-10 otra vez, pero al revés |
| `viewport/PostFX.tsx` | `Scene3D` monta `SubsurfaceAOEffect`, que usa el mismo `@react-three/postprocessing` | **Segunda pila de postprocesado superada por la que se entrega** — el mismo patrón que `InstancedSegmentsLayer` |

**Y aquí la fase de limpieza se detiene a propósito, salvo en el cuarto caso.** Sólo `PostFX` es lo que esta fase sabe resolver: un duplicado superado, que no deja varado nada. Los otros tres **no son código muerto: son funciones terminadas a las que les falta el último cable**, y borrarlas destruiría la única UI escrita para cosas que el backend ya sabe hacer — lo contrario de lo que persigue el plan. Montarlas es una decisión de producto con su QA visual, y ya tiene fase dueña: **la Fase 9**, que existe exactamente para esto («5 endpoints de F7 sin consumidor; el gate midió el backend, no al usuario») y que además añade el criterio obligatorio *«un usuario puede hacer/ver X desde la UI»*. Quedan **registrados aquí con su medición**, que es la diferencia entre una decisión y un limbo.

**Gate del cierre:** `compileall` OK · **2.382 tests colectan** sin error de import · presupuestos AST OK · cierre de dependencias OK (105 distribuciones) · inventario de validación OK (66 scripts) · `test_fase6_limpieza_verificada.py` **48 passed** · frontend `tsc --noEmit` **0**, `eslint` de fuentes **0 errores**, `next build` **OK**.

**La suite COMPLETA del backend, no una selección: 2.439 tests en 2h07 → 2.367 passed, 70 skipped, 2 failed.** (Los 77 archivos afectados se corrieron además por separado: 1.095 passed, 6 skipped, los mismos 2 failed.) Los dos fallos son **los mismos** en ambas corridas.

**Los 2 fallos, medidos en vez de atribuidos.** Ninguno lo causa este cierre, y no se dice por argumento sino por A/B: se devolvieron a su versión de `HEAD` **sólo** los 9 archivos de código que tocó la fase —dejando intacto el trabajo sin commitear de la Fase 4— y se repitieron los dos tests.

| Test | Con el cierre | Sin el cierre (A/B) | Veredicto |
|---|---|---|---|
| `test_fase7_wiring::test_e2e_enabled_changes_model_and_reports` | FALLA `max_diff=9,10e-05` vs umbral `1e-4` | **FALLA idéntico** | **No es del cierre.** Corre tres inversiones completas y mide cuánto mueve el modelo el prior geológico; pasa por `solve_inversion_lsqr`, **la función cuya cadena de pesos reescribió la Fase 4 sin commitear**. Falla por un 9% por debajo del umbral |
| `test_fase4_depth_weighting::test_effective_model_weight_is_column_sensitivity_not_depth_weighting` | FALLA en la suite (`1,78e-03` vs `1e-6`) | **PASA aislado, en ambos brazos** | **No es una regresión de código, es orden de ejecución.** El test pasa solo y falla dentro de la suite completa: hay contaminación entre tests. El instrumento de la Fase 4 no es fiable mientras dependa del orden |

Que el borrado no pueda mover estos números era predecible —cada símbolo eliminado tenía **cero referencias**, así que no hay ruta de ejecución que cambiar— pero *predecible* no es *medido*, y la regla del proyecto es medir. **Ambos quedan como trabajo abierto de la Fase 4, no de la 6:** el primero exige decidir si el umbral `1e-4` describe el efecto real del prior tras la reescritura de pesos; el segundo, encontrar qué test contamina a cuál (probablemente estado global o `data/projects/` compartido) — porque **un test que sólo pasa cuando corre solo no defiende nada en la CI**.

---

---

## FASE 7 — Terminar la extracción compartida de los dos motores · **M** · 🟠 P1

*(antes «Fase B-0» — renumerada para que el rótulo sea el orden de ejecución.)*

*(Fase nueva, derivada de H-9. Es el primer paso de la Fase 8 y prerrequisito del cableado de la Fase 4.)*

**Objetivo.** Que la cadena de pesos, el σ adaptativo, el bucle IRLS y los diagnósticos numéricos vivan **una sola vez**, compartidos por gravimetría y magnetometría — y que **el funcional de regularización sea explícito y declarado**, no una consecuencia accidental de qué opciones estén activas.

> **Ampliado tras la 8ª pasada (H-33).** Esta fase ya no es solo anti-duplicación. Hoy hay **tres comportamientos distintos del mismo parámetro** `depth_beta`: anulado en gravimetría por `Ws`, activo en la ruta magnética sin padding, inerte en la ruta magnética con padding. El entregable central pasa a ser una única función `build_model_weights(...)` que **decida y declare** si el peso de profundidad entra en el funcional. Hoy esa decisión la toma, sin que nadie lo advierta, la presencia del padding.

**Justificación.** **[MEDIDO]** 228 ventanas duplicadas. El módulo correcto ya existe (`exploration/geophysics_weights.py`) con 65 líneas y 3 funciones: **la decisión arquitectónica ya se tomó y se abandonó al 3%**. No hay que diseñar nada nuevo, hay que terminar.

**Diseño.** Promover a `geophysics_weights.py` (o un `potential_field_core.py` hermano): `_sigma_adaptive`, la construcción de `Wd/Wz/Ws`, el ensamblado del sistema aumentado, el bucle IRLS de minimum-support y el estimador de `cond(A)`. Gravimetría y magnetometría conservan **solo** lo que las diferencia: el forward (prisma Nagy vs Bhattacharyya), el manejo de remanencia/MVI y sus unidades.

**Estrategia de pruebas.** **Byte-identidad obligatoria** en los 4 benchmarks + la suite de magnetometría. Un solo bit de diferencia ⇒ revertir.

**Criterios de aceptación.** (a) Ventanas duplicadas gravimetría↔magnetometría < 40 (desde 228), medido con el mismo script (`study_duplication.py`) como gate. (b) Suite verde y benchmarks byte-idénticos. (c) **Un test que fije el funcional: para cada motor y cada configuración (con y sin padding, con y sin anclajes, L2 y compacto), variar `depth_beta` produce el efecto declarado — o ninguno, si así se decide.** Hoy ese test fallaría en tres de las combinaciones y nadie lo sabía. (d) La corrida declara en su salida qué funcional usó.

**Riesgo.** Medio-alto: toca los dos motores validados. Mitigación: byte-identidad y comparación mecánica antes/después.

---

### ✅ EJECUTADA — 2026-08-15

**Los cuatro criterios, con su número.**

| Criterio | Estado | Medido |
|---|---|---|
| (a) ventanas duplicadas grav↔mag < 40 | ✅ | **192 → 20** (`scripts/ci/study_duplication.py`, con gate y línea base congelada) |
| (b) suite verde y byte-identidad | ✅ | **34/34 casos byte-idénticos** (SHA-256 sobre los bits de float64), salvo 2 cambios deliberados |
| (c) test que fija el funcional por motor y configuración | ✅ | `tests/test_fase7_nucleo_compartido.py`, **15 tests**, 5 configuraciones magnéticas + gravimetría |
| (d) la corrida declara qué funcional usó | ✅ | `solver_meta["regularization_functional"]` en los **tres** solvers, y en el reporte del servicio |

**El script del criterio (a) no existía.** El informe citaba `study_duplication.py` como el medidor con el que verificar el gate, pero era una herramienta ad-hoc del auditor que no quedó en el repositorio: el criterio no era verificable. Se reconstruyó desde el método descrito (tokens normalizados, ventanas de 12 líneas, huella criptográfica). Barre **114 archivos — el mismo número que el informe**, lo que da confianza en que mide lo mismo; pero midió **192** ventanas donde el informe decía 228. La diferencia es honesta y tiene dos causas: los detalles finos del medidor original no están escritos (por eso éste congela su propia línea base en vez de heredar un número), y las Fases 4 y 6 ya habían borrado código de ambos motores. **Lo que el gate defiende es la propiedad —«la duplicación no vuelve a subir»— con un medidor estable, no un número heredado de una herramienta perdida.**

**Lo que se extrajo, y por qué el conteo subió antes de bajar.** El núcleo compartido es `exploration/potential_field_core.py`: σ adaptativo, máscara de celdas activas, dominio observable R-05, mapeo de intervalos de sondaje y litología, `build_model_weights`, peso de fila por profundidad, estimador de `cond(A)`, reponderación IRLS de minimum-support, modelo de referencia, operador de suavizado, ensemble del null-space shuttle, ecuaciones normales, update de Woodbury, sub-región del live-update y misfit ponderado. A mitad de camino el conteo subió de 192 a **106**: al sustituir bloques largos y divergentes por llamadas cortas e idénticas, la estructura compartida que quedaba debajo se hizo visible para el medidor. Eso no fue un retroceso, fue el diagnóstico de lo que faltaba extraer.

**Los dos motores adelgazaron 277 líneas y el núcleo pesa 883** — de las cuales **408 (46 %) son docstrings y comentarios** que dejan escritas las mediciones de esta fase. El presupuesto AST de `exploration` sube de 10.475 a 11.081 LOC y se actualiza a propósito. A cambio, **la complejidad ciclomática máxima del paquete baja de 143 a 124**, que es la dirección en la que la Fase 8 tiene que seguir.

---

#### Hallazgo 1 — el escáner de λ medía con un operador que ya no existía, y nadie lo había cuantificado

§9D.2 dejó esta medición escrita como pendiente y la llamó *«verificación decisiva y barata (una tarde)»*: registrar el χ² que el escáner predice para el λ elegido y el χ² que el solve consigue con ese mismo λ. **Nadie la corrió.** Esta fase la corrió (`scripts/validation/fase7_lambda_identity_probe.py`):

| profundidad | χ² prometido | χ² real del solve | ratio | ¿acertó el λ? |
|---|---:|---:|---:|:--:|
| 150 m | 2,084 | 48,53 | **23×** | NO |
| 350 m | 0,444 | 128,5 | **289×** | NO |
| 550 m | 0,0724 | 165,7 | **2.290×** | NO |
| 750 m | 0,0161 | 204,5 | **12.700×** | NO |

**0 de 4**: el escáner nunca eligió el λ que el solver real habría elegido. Y el error **crece con la profundidad** — exactamente el mecanismo que §9D.2 planteó como hipótesis no descartada, ahora con número.

Eran **cuatro** desajustes, no uno: (1) el escáner pesaba el Laplaciano por `w_reg` y el solver no; (2) su smallness era `diag(λ·w_reg)·Ws` —espacio físico, relajada con la profundidad— y la del solver es identidad en `m̃`; (3) usaba λ crudo y el solver `λ·√(n/256)`; (4) **calculaba su χ² con un σ que el llamador no controlaba**, y χ² es literalmente `Σ(r/σ)²/n`.

El comentario `gravimetry.py:1664` documentaba haber arreglado este mismo desajuste una vez («*el χ² del trial divergía ~700× del χ² real del solve*»). La Fase 4 quitó `w_reg` del solver y **nadie actualizó el escáner: el bug volvió en silencio, por el mecanismo que su propio comentario advertía.**

**Después del arreglo**: ratio **1,12–1,70** y **4/4** en la elección de λ. Y con el box petrofísico abierto —el brazo de control que aísla la única diferencia que le queda al escáner, porque no modela bounds— el ratio es **1,0000 a las cuatro profundidades**. La identidad es exacta; lo que resta es el bound, medido, no supuesto.

**Alcance, para no exagerar el hallazgo:** producción **no** usa este selector (lo rodea desde Tier 1 A2 escaneando con el solver real, y la propia auditoría lo rectificó). Lo arreglado es el **instrumento de diagnóstico**, que es lo que H-25 dejó abierto. Es también el único cambio de comportamiento de toda la fase: 2 de los 34 casos del arnés cambiaron a propósito, y sus huellas anteriores quedaron conservadas en `fase7_byte_identity_baseline.pre_fase7_lambda.json`.

---

#### Hallazgo 2 — el caveat que H-33 dejó sin cuantificar vale el 86 %, no un redondeo

§9G.1 cerraba con esto:

> *«en la ruta B, `Wz_inv` sigue siendo un precondicionador por la derecha legítimo […] si trunca por iteraciones, habría un efecto residual de regularización implícita por parada temprana. **No lo cuantifiqué.**»*

**[MEDIDO]** Se cuantificó, y cambia la lectura de H-33:

* la solución **exacta** de la ruta B (por `lstsq` denso) es invariante en β a **1e-11** — H-33 tiene razón **sobre el funcional**;
* pero el LSQR del motor termina con **`istop=7`** (límite de iteraciones) en **500/500 para todo β**, y queda a **54 %–269 %** de la exacta;
* de modo que mover β de 0,5 a 3,0 cambia la susceptibilidad recuperada un **66 %–86 %**.

**No es ruido de punto flotante: es casi toda la señal.** Y el mecanismo no es el solver proyectado —se comprobó con FISTA apagado y el efecto se mantiene—, es dónde se detiene el LSQR.

Esto obliga a un matiz que la declaración no podía omitir: **«inerte» era cierto del álgebra y falso de la corrida.** `declare_functional` distingue ahora los dos casos y, cuando el peso es cambio de variable puro **pero el solver no convergió**, declara `depth_beta_has_effect: true` con `effect_mechanism: "early_stopping"` y el motivo en español.

**Y de paso:** los dos motores **descartaban el criterio de parada de LSQR** (`istop`, `itn`). Una corrida que se rinde por límite de iteraciones era indistinguible de una que convergió. Ahora se publican (`lsqr_istop`, `lsqr_iters`, `lsqr_converged`).

---

#### Hallazgo 3 — había un TERCER sitio construyendo el peso de modelo

`solve_inversion_treemesh` (el solver Octree, al que producción conmuta **sola** con >50.000 celdas o >50 km de survey) tenía su propia cadena de pesos escrita a mano. Es el caso que §9.1884 describe: *«la misma configuración nominal aplica un depth weighting o ninguno según el tamaño del levantamiento, y nada en la salida lo declara»*. Quedó recableado al mismo constructor y **declara su funcional**, que es el opuesto al del solver de grilla regular: allí `w_reg` va sólo en la smallness y la suavidad, no en el bloque de datos, así que **no se cancela y `depth_beta` está VIVO** (la Fase 4 lo midió: 8.125×). Dos corridas del mismo producto sobre mallas de distinto tamaño ya no son incomparables en silencio.

---

#### La regla, en un sitio y en una línea

Toda la física de la declaración es esto: **un peso `W` que multiplica *todos* los bloques del sistema aumentado es un cambio de variable puro y no cambia la solución exacta; sólo actúa si algún bloque —en la práctica, la smallness— queda sin él.** De esa única regla salen las tres filas que H-33 midió, sin que nadie tenga que acordarse de mirar si el padding está encendido:

| Motor / ruta | `smallness` | `depth_beta` en el funcional | Declarado |
|---|---|---|---|
| Gravimetría, grilla regular | identidad en `m̃` | ❌ (el peso es `‖col_j(W_d·G)‖`, sensibilidad) | `model_weight_kind: sensitivity` |
| Magnetometría RUTA A (sin padding/anclas/IRLS) | identidad en `m̃` | ✅ | `depth_weighting_active: true` |
| Magnetometría RUTA B (producción) | `diags(w)·W` | ❌ en el funcional; ⚠️ **sí en el resultado si el solver trunca** | `effect_mechanism: early_stopping` |
| Gravimetría, solver Octree | `diags(λ·w_reg)·Ws` (peso de FILA, no se cancela) | ✅ | `effect_mechanism: row_weight_...` |

La corrida publica además a qué Li & Oldenburg equivale **su** malla, con la desviación del ajuste. La Fase 4 midió β≈2,63 con 5,3 % de desviación **una vez, a mano, sobre la malla del producto**; ahora cada corrida lo mide sobre su propia geometría — y en mallas pequeñas la desviación sale alta, que es justo la información que hacía falta para saber cuándo ese número significa algo. **β_eq=2,63 es una propiedad de la malla del producto, no una constante universal.**

---

#### Lo que NO se hizo, y por qué

* **No se cambió la física de ninguna ruta de producción.** El criterio (c) admite explícitamente *«o ninguno, si así se decide»*, y el criterio (b) exige byte-identidad. Se conserva la física validada (DO-27, Raglan, San Nicolás) y se declara la verdad sobre ella. Encender el depth weighting en la ruta B magnética es un cambio de funcional que exige su propio barrido medido — como el que la Fase 4 hizo para gravimetría — y **no cabe en una fase cuyo criterio duro es no mover un bit**.
* **No se tocó el frontend.** La declaración viaja en el reporte de la corrida; mostrarla al usuario es trabajo de la **Fase 9**, que es la que introduce el criterio *«un usuario puede ver X desde la UI»*. Añadido a su lista.
* **No se borraron los dos selectores de λ**, que era la otra opción que §9D.2 ofrecía. Se arreglaron: un instrumento que mide bien vale más que uno borrado, y ahora hay un test que impide que vuelva a desalinearse.
* **`iter_lim=500` no se subió.** El Hallazgo 2 dice que el LSQR magnético no converge en 500 iteraciones en la malla de prueba. Subirlo cambia resultados en producción; medirlo y decidirlo es trabajo propio, no un efecto colateral de una fase de extracción. **Queda como deber medido para la Fase 8.**

---

## FASE 8 — Partir la espina dorsal · **L** · 🟠 P1

*(antes «Fase B» — renumerada para que el rotulo sea el orden de ejecucion.)*

**Objetivo.** Que ninguna función del camino crítico supere ~300 LOC ni CC 40, **sin cambiar un solo resultado numérico**.

**Justificación.** 21 funciones concentran el 26,4% del código. Cada feature nueva paga un impuesto creciente y el riesgo de regresión silenciosa es estructural.

**Dependencias.** Fase 3 (red de seguridad) **debe ir antes o en paralelo**. Refactorizar sin la regresión física automática sería temerario.

**Diseño propuesto (orden estricto, un commit por paso, byte-identidad verificada en cada uno):**

1. `run_geophysics_inversion` (1.996 LOC) → extraer, en este orden: `_prepare_mesh_and_topography`, `_build_priors_and_anchors`, `_execute_solver`, `_build_reports` (B1/B2/B3 ya son funciones sueltas; falta el orquestador que las llama), `_persist_artifacts`.
2. `invert_gravity_csv` (927 LOC, 41 args) → el handler HTTP debe quedar en <100 LOC: validar, delegar, serializar. **Agrupar los 41 parámetros en objetos Pydantic cohesivos** (`MeshConfig`, `RegularizationConfig`, `AnchorConfig`, `DataWeightConfig`).
3. `solve_inversion_lsqr` (1.050 LOC, 39 args) → **el más delicado.** Extraer sin tocar la aritmética: `_build_active_mask`, `_map_boreholes_to_cells`, `_build_weight_chain`, `_assemble_augmented_system`, `_run_irls_loop`. Los mismos objetos de configuración del paso 2.
4. Eliminar los `from core.config import ...` del interior del solver: la configuración se resuelve **una vez, arriba**, y baja como parámetros explícitos.

**Cambios arquitectónicos.** Introducir la frontera *orquestación de corrida* ↔ *física de inversión* (informe 09 §4.1). Definir `ForwardOperator` y `Solver` como protocolos, aunque hoy tengan una sola implementación: es lo que permitirá la segunda física sin otro monolito.

**Estrategia de pruebas.** **Byte-identidad como criterio duro**: congelar salidas de los 4 benchmarks + 10 sintéticos ANTES de tocar nada, y verificar igualdad exacta tras cada commit. Si un paso cambia un bit, se revierte y se investiga.

**Criterios de aceptación.** Métricas AST post-refactor: máx LOC ≤300, máx CC ≤40, máx args ≤12. Suite completa verde. Los 4 benchmarks byte-idénticos.

**Riesgos.** Altos por naturaleza. Mitigación: byte-identidad, commits atómicos, y **prohibido combinar con cambios de comportamiento** (Fase 4 va antes o después, nunca durante).

### ✅ EJECUTADA — 2026-08-16

**Estado: los 4 pasos del diseño están hechos y verificados. La espina está partida.**

| | antes | después | verificación |
|---|---|---|---|
| `run_geophysics_inversion` | 2.030 LOC · CC **183** | **152 LOC · CC 12** | 28/28 byte-idéntico |
| `invert_gravity_csv` | 927 LOC · CC 165 · **41 args** | **54 LOC · CC 7 · 9 args** | contrato HTTP campo a campo |
| `solve_inversion_lsqr` | 1.046 LOC · CC 124 | **212 LOC · CC 12** | 34/34 byte-idéntico |

**Lo primero fue construir el instrumento, y lo primero que midió fue que el instrumento anterior no servía.** El arnés de la Fase 7 (`fase7_byte_identity.py`, 34 casos) mide los MOTORES. Se comprobó mutilando `run_geophysics_inversion` a propósito: **34/34 en verde**. Es decir, la red de la fase anterior no ve nada de lo que ésta toca. Por eso se escribió `scripts/validation/fase8_byte_identity.py`: **28 configuraciones** que llaman al servicio y al endpoint reales y hashean con SHA-256 (a) el payload completo canonicalizado —los `float` por `repr`, roundtrip exacto de float64— y (b) los **bits de las columnas numéricas del parquet** que queda en disco, que es el producto de verdad.

**Congelar la línea base costó tres correcciones, y las tres eran defectos del arnés que habrían dejado pasar un refactor roto:**

1. `favorability.computed_at` hacía que dos corridas idénticas dieran hashes distintos → se normaliza el valor (no se borra la clave: la presencia del campo sigue comparándose).
2. `importMetadata.source_file` lleva el UUID del temporal → misma normalización.
3. **Los 7 casos de API daban el MISMO hash**: los siete morían en el gate de *spatial readiness* (422) sin llegar a invertir. Un arnés que mide el mismo 422 siete veces habría dado «byte-identidad OK» con el endpoint destrozado.

**El método: no se reescribió ni una línea.** Partir 4.000 líneas con byte-identidad como criterio duro obliga a mover texto, no a mejorarlo. Los cuerpos de cada helper son **las mismas líneas** del monolito; las entradas y salidas de cada bloque **no se dedujeron leyendo, se calcularon con AST** (variables leídas antes de asignarse dentro del rango = entradas; asignadas y leídas después = salidas). Auditoría posterior: **0 sentencias del original perdidas** en `gravimetry.py` (comparación multiconjunto de líneas de código, ignorando indentación).

**Tres cosas que el diseño no anticipaba, medidas:**

* **Morozov re-liga λ, y partir la función rompía eso en silencio.** En el monolito `_lambda_mag` se re-asignaba en el mismo scope y todo lo de abajo —PGI, DOI, checkerboard, σ posterior, el reporte— veía el valor nuevo. Al extraer el solver, deja de ser automático. Sin la escritura de vuelta, el refactor habría sido *el mismo código con otra λ*: la clase de regresión que ningún test de contrato detecta. Lo cazó el arnés, no una revisión.

* **[CORRECCIÓN AL PLAN] Agrupar los 41 parámetros «en objetos Pydantic» —leído literal— ROMPE el contrato HTTP.** Con FastAPI 0.135, `Annotated[Modelo, Form()]` hace que el formulario deje de tener campos planos (`nx`, `ny`, `lambda_mag`…) y pase a exigir un campo `malla` con el objeto dentro; medido con endpoint plano vs agrupado lado a lado (`422 Field required`). El frontend dejaría de poder invertir. Lo que **sí** conserva el contrato es construir los mismos objetos con `Depends`: comprobado campo a campo, incluidos los defaults y el esquema OpenAPI — **40 campos, idénticos**. Con eso la firma baja de 41 a 9 y el handler queda en **54 líneas** (el diseño pedía <100).

* **[CORRECCIÓN AL PLAN] El paso 4 no puede subir la configuración a nivel de módulo.** El texto dice «eliminar los `from core.config import ...` del interior del solver». Estaban dentro del **bucle IRLS** (se re-ejecutaban en cada reponderación) y de ahí salieron. Pero **no suben al módulo**: `wz_separation_probe.py`, `wz_beta_liveness_gravimetry.py`, `fase7_byte_identity.py`, `tests/generate_validation_report.py` y `test_benchmark_checkerboard.py` fijan esas perillas escribiendo el **atributo** de `core.config` justo antes de llamar — uno de ellos lo documenta: *«gravimetry lo importa dentro del bucle»*. Un import de módulo congelaría el valor en el arranque y esas sondas medirían en silencio la configuración equivocada: el mismo modo de fallo que la Fase 5 encontró en `bounded_solver_active`. Se leen **una vez por llamada**, y hay un test que lo afirma en los dos sentidos.

**El deber medido que dejó la Fase 7: `iter_lim=500`. Decisión: NO se sube, y el motivo no es el que se esperaba.**

`scripts/validation/fase8_iter_lim_probe.py` resuelve cada motor con `iter_lim` ∈ {500, 1000, 2000, 5000} y mide por qué paró, cuánto cambia el modelo y cuánto cuesta:

| caso | istop@500 | itn | Δmodelo vs 500 (1000 / 2000 / 5000) |
|---|---|---|---|
| grav λ=0,316 | **2** (converge) | 40 | 0 · 0 · 0 |
| grav λ=0,316 + padding | **2** | 33 | 0 · 0 · 0 |
| grav λ=0,01 | **2** | 232 | 0 · 0 · 0 |
| mag λ=1e-3 | **7** (se rinde) | 500 | 18,5 % · 29,3 % · 25,0 % |
| mag λ=1e-3 + padding | **7** | 500 | 33,2 % · 56,9 % · **66,1 %** |
| mag λ=1e-2 | **7** | 500 | 16,9 % · 24,2 % · 20,8 % |

* **En gravimetría el límite no ata**: LSQR para por tolerancia a las 33–232 iteraciones y subir el techo cambia el modelo en **0,000e+00 exacto**. El hallazgo de la Fase 7 era magnético, y sólo magnético.
* **En magnetometría subir el límite no da una respuesta mejor: da una distinta.** A las 500 iteraciones el χ² ya está en **1e-14 – 1e-16** — el dato está ajustado a precisión de máquina. Las iteraciones extra no mejoran el ajuste: mueven el modelo por el **espacio nulo**, hasta un **66 %**. Y con padding —el régimen de producción— **ni a 5.000 converge** (`istop=7`, 5000/5000).
* Por eso subirlo sería cambiar el resultado sin justificación física, y además pagando ~8× en tiempo. **La cura no son iteraciones: es regularización** (λ=1e-2 se comporta igual que 1e-3, o sea que las magnitudes actuales de λ no restringen el espacio nulo magnético). Eso es decisión de física y no entra en una fase de byte-identidad.
* **Lo accionable y barato ya existe**: la corrida publica `lsqr_istop` y `lsqr_converged` desde la Fase 7. Un resultado que se rindió y no lo dice es el patrón de H-27. **Mostrarlo es trabajo de la Fase 9**, que ya lo tiene anotado.

**Un defecto reachable que el arnés destapó sin buscarlo (NO se arregla aquí).** Al construir el caso con topografía activa, la corrida **revienta con `TypeError`** y el endpoint devuelve 500. Mecanismo, medido:

1. Con topografía, la capa superior del núcleo son celdas de **aire** (36 de 216 en el caso medido) y su `visual_score` es `NaN`.
2. **Polars ordena `NaN` por encima de cualquier número**, así que el filtro de anomalías `visual_score >= 0.35` selecciona **exactamente las celdas de aire** — y sólo ésas, porque ningún vóxel vivo llegaba al cutoff (máx. 2,69 vs 2,75).
3. `build_voxel_output` las serializa a propósito con `density: None`.
4. `build_geophysics_report` filtra las inactivas… y su **«fallback defensivo»** (`if not active_voxels: active_voxels = voxels`) devuelve justo la lista de `None`, que la línea siguiente pasa por `float()`.

O sea: **el guardia que debía proteger el cálculo es lo que lo mata**, y el conjunto de anomalías puede estar hecho de aire sin que nada lo diga. Se ha **congelado como fallo** en la línea base (`servicio/topografia` → `ERROR::TypeError`) para que el refactor tenga que conservarlo bit a bit; arreglarlo es un cambio de conducta y esta fase lo tiene prohibido. Es de la familia de la Fase 1 (*«resultado equivocado con cara de correcto»*) y debería ir en su propio commit, con su medición antes/después.

**Un SEGUNDO hallazgo, y éste es peor: la misma entrada puede dar dos modelos.** Al verificar el paso 2 apareció un caso de API que no reproducía. Se corrió **tres veces seguidas sobre el mismo código**: `76434aaf…`, `f7848157…`, `f7848157…`. **No es el refactor** — dos de las tres reproducen exactamente la línea base anterior a tocar nada, y el caso equivalente a nivel de servicio (`servicio/lambda_morozov`, que también corre Morozov) es estable en todas las corridas medidas. Es decir: **por la ruta HTTP, el mismo CSV y el mismo formulario pueden devolver dos modelos distintos**, con `lambda_mag=0` + `gravimeter_type` declarado (la ruta de Morozov, 6 solves). Para una herramienta de targeting eso es de la familia del peor hallazgo posible: no es que el número sea aproximado, es que **no es reproducible**. Se deja **midiéndose** en el arnés (`INESTABLES`, el hash se congela y se imprime) pero **fuera del veredicto**, porque un gate que falla una de cada tres veces sin que nadie toque nada acaba desactivado y entonces tampoco defiende lo que sí es estable. Diagnosticarlo es trabajo propio: **no se toca aquí** porque esta fase tiene prohibido cambiar comportamiento, y porque la causa aún no está aislada (el envoltorio de heartbeat sólo escribe estado; el bucle de Morozov es determinista en el papel).

**Lo que queda fuera, medido y con nombre.** El criterio de aceptación pide «máx LOC ≤300, máx CC ≤40, máx args ≤12» por métrica AST. Para las **tres funciones del camino crítico** se cumple. Para el **máximo por paquete** no, y los ofensores restantes están **fuera de los cuatro pasos** del diseño:

| función | LOC | CC | por qué no entró |
|---|---|---|---|
| `exploration/magnetometry.py::solve_magnetic_inversion_lsqr` | 812 | 116 | el gemelo magnético; misma forma, mismo método aplicable |
| `services/gravity_import_service.py::_import_gravity_csv_v1_impl` | 777 | **181** | ingesta CSV, no la espina de inversión |
| `services/joint_inversion.py::run_joint_inversion` | 736 | 87 | inversión conjunta |
| `services/geophysics_service.py::run_magnetic_inversion` | 616 | 73 | orquestador magnético |

Y **`args_max` sigue en 38** en `exploration`: es la firma pública de `solve_inversion_lsqr`, que llaman producción, los tests y **diez sondas de validación**. Estrecharla es un cambio incompatible que congelaría firmas justo antes de la **Fase 11** («API de scripting»), y la propia auditoría advierte de eso: *«conviene marcarla v0 hasta después de la Fase 8, para no congelar firmas que el refactor va a cambiar»*. Se deja explícito en vez de disfrazarlo con `**kwargs`, que bajaría el número sin mejorar nada.

**Instrumentos que deja la fase**

* `scripts/validation/fase8_byte_identity.py` + su línea base (28 casos) — servicio y API, con el parquet incluido.
* `scripts/validation/fase8_iter_lim_probe.py` + `fase8_iter_lim_report.json` — la medición que cierra el deber de la Fase 7.
* `tests/test_fase8_espina_dorsal.py` (11 tests) — techos **por nombre** del camino crítico, los 40 campos del formulario de `/invert`, la configuración fuera del bucle *y* fuera del módulo, y los protocolos.
* `scripts/ci/ast_budgets.py` ahora mide **`args_max`**: el gate vigilaba longitud y ramas mientras una función llevaba 41 parámetros.
* `exploration/protocols.py` — `ForwardOperator` y `Solver` como protocolos estructurales. Al escribirlos apareció que no hay «una sola implementación» como suponía el diseño: hay **cuatro solvers** con la misma forma y ninguna firma común declarada.

---

---

---

## FASE 9 — Interfaz para F7 y gates con criterio de usuario · **M** · 🟠 P1

*(antes «Fase H» — renumerada para que el rotulo sea el orden de ejecucion.)*

*(Fase nueva, derivada de H-10.)*

**Objetivo.** Que licenciamiento, exportación de diagnóstico y honestidad offline sean **usables**, y que ningún gate futuro vuelva a declarar cerrada una fase sin camino de usuario.

**Justificación.** **[MEDIDO]** 5 endpoints de F7 sin consumidor. Hoy un cliente no puede activar su licencia ni enviar un diagnóstico cuando algo falla — precisamente las dos cosas que un producto local-first vendido a terceros necesita para operar comercialmente. **Bloquea la monetización, no solo la usabilidad.**

**Trabajo.** (1) Panel de licencia: estado, activación por pegado de clave, tier vigente. (2) Botón "exportar diagnóstico" en el modal de error y en ajustes. (3) Indicador de conectividad honesto en la barra de estado. (4) **[H-27, prioritario dentro de esta fase] Superficie de degradaciones físicas:** que el fallback a topografía plana —y cualquier otra degradación con motivo nombrado ya registrada en el backend— emita un `warnings[]` y se muestre junto al resultado, no solo en el log. El canal existe; falta usarlo y montar `WarningBanner` también en la vista de resultados. (5) **Cambio de proceso:** añadir a la plantilla de gate de fase un criterio obligatorio *"un usuario puede hacer/ver X desde la UI"*, y auditar retroactivamente los gates de F5–F8 contra él.

> **Ampliado por el cierre de la Fase 6 (2026-08-14) — tres paneles ya escritos que sólo hay que montar.** Al medir los módulos TS/TSX sin importador aparecieron tres superficies terminadas y nunca montadas, y en dos casos son la ÚNICA UI de una función del backend que hoy queda varada. Es H-10 otra vez, pero al revés: allí eran endpoints sin UI; aquí es UI sin montar. **Es el trabajo más barato de esta fase, porque el código ya existe:**
> - **`viewport/SliceControls.tsx`** — nadie más escribe el estado del corte, mientras `SectionPaintLayer` **sí** está montada en `Scene3D` y `/api/section` responde. O sea: el plano de corte tipo Leapfrog está construido de punta a punta y **no hay nada que lo encienda**.
> - **`viewport/MultiPhysicsControls.tsx`** — `setViewMode` sólo se llama desde este panel y desde `packageInversion.ts:288`, que lo fija automáticamente según la física invertida. Hoy **el usuario no puede cambiar de vista a mano** (densidad / susceptibilidad / incertidumbre).
> - **`MultimodalComboPanel.tsx`** — único consumidor de `/api/multimodal/plan`: la función multimodal de la Fase 21 tiene UI escrita y sin montar.
>
> Los tres entran de lleno en el criterio de proceso que esta fase introduce (*«un usuario puede hacer/ver X desde la UI»*), y son la prueba de que ese criterio hacía falta: **pasaron los gates de sus fases sin que nadie notara que no había forma de llegar a ellos**.

> **Añadido por el cierre de la Fase 7 (2026-08-15) — el funcional declarado necesita superficie.** La Fase 7 hizo que cada corrida publique **qué funcional de regularización usó**: `regularization_functional` viaja ya en el reporte del servicio, con `depth_weighting_active`, `effect_mechanism`, `solver_converged` y el motivo escrito en español. Hoy sólo llega al JSON. Dos cosas concretas para esta fase:
> - **Mostrar el funcional junto al resultado.** Es lo que hace comparables dos corridas: la misma configuración nominal aplica un depth weighting o ninguno según haya padding, y ahora la corrida lo dice — pero el usuario no lo ve.
> - **Avisar cuando el solver no convergió.** La Fase 7 midió que el LSQR magnético termina por límite de iteraciones (`istop=7`, 500/500) y que eso hace que un parámetro inerte en el papel mueva el resultado hasta un 86 %. `lsqr_converged` ya está en la salida. **Un resultado que no convergió y no lo dice es el mismo patrón que H-27**: el backend registra la degradación con un motivo nombrado y el camino del usuario se detiene ahí.

**Criterios de aceptación.** Un tester que no conozca el código activa una licencia, exporta un diagnóstico y ve su estado de conexión, sin tocar la API a mano. Playwright cubre los 3 recorridos. **Y un test de integración que fuerce el fallo de topografía verifica que el aviso aparece en la respuesta y en la UI** — no que se escribió en el log. **Más, del cierre de la Fase 6:** el usuario puede encender el plano de corte y cambiar de vista a mano, con su recorrido Playwright.

**Riesgo.** Bajo (frontend puro sobre backend probado). **Dependencia:** iteración separada frontend, según la regla del repo.

---

### ✅ EJECUTADA — 2026-08-16

**Los 5 puntos del trabajo, hechos.** Ejecutada en tres iteraciones separadas
(backend / frontend / proceso) por la regla del repo. Gate: **tsc 0 · eslint 0
errores · 25/25 Playwright** (13 recorridos nuevos + los 12 previos, incluida la
regresión visual) · **45 tests de backend** entre los nuevos y los tocados.

**(4) H-27 ya estaba cerrado por la Fase 1, y verificado aquí.** El canal
`warnings[]` viaja, `WarningBanner` está montado y hay pytest + Playwright a los
dos lados. Lo que faltaba lo encontró la medición de esta fase y se arregló: el
banner vivía **dentro** de la rama `showModel` y el fetch exigía
`status === "ready"`, de modo que los avisos desaparecían justo cuando no hay
modelo que pintar —una corrida en error, un solver que no converge—, que es
cuando más hacen falta.

**Tres superficies montadas** (`SliceControls`, `MultiPhysicsControls`,
`MultimodalComboPanel`), y con ellas el plano de corte tipo Leapfrog queda
alcanzable de punta a punta por primera vez. **Componentes `.tsx` sin ningún
importador: 3 → 0, medido.**

#### Cinco defectos NUEVOS, todos medidos (ninguno estaba en el plan)

1. **`copilot_gemini.configured` era `False` constante.** `connectivity_service`
   leía `config.GEMINI_API_KEY`, un atributo que **no existe** en `core/config.py`,
   protegido con un `hasattr` que lo convertía en un False silencioso. La clave
   real la resuelve `chat_api::_resolve_api_key` desde el entorno. Además el
   copiloto es **BYO-key** (la clave se pega en la interfaz): «no configurado» no
   significa «no disponible», y ahora hay campo propio (`user_supplied_key`) para
   que la UI no mienta por omisión.
2. **`probed: true` sin haber tocado la red.** El endpoint aceptaba `probe=True`,
   lo reflejaba como sondeo hecho, y **el sondeo nunca se implementó**. Se dice la
   verdad (`probed:false` + `probe_requested` + `probe_note`) en vez de añadir una
   llamada de red al servicio que certifica que el producto es offline. Los tests
   que había pasaban con la mentira dentro porque sólo miraban el caso por defecto.
3. **Un «Online» fijo en el copiloto.** `IAChatView` pintaba un punto verde
   palpitante y la palabra *Online* escritos en el JSX, sin comprobar nada.
4. **`≤150` iteraciones inventadas en el frontend.** `SolverDiagnosticsWidget`
   afirmaba ese máximo justo cuando el backend **no** reportaba iteraciones —y las
   rutas de producción usan 500/600/800—, enmascarando el `500/500` que es la
   evidencia de no-convergencia. Física inventada en TS: viola la Regla de Oro.
5. **`MultimodalComboPanel` tumbaba la pestaña.** Escrito en la Fase 21 y jamás
   importado, nunca se había ejecutado contra una respuesta real: leía
   `plan.confidence_pct.toFixed()` y `plan.resolution_priority.join()` a pelo. Con
   un plan incompleto es un TypeError en render y **se cae la página entera**
   («This page couldn't load»). Montarlo tal cual habría metido en el camino
   dorado justo lo que el invariante «nunca crashea» prohíbe.

#### (5) El cambio de proceso, MEDIDO en vez de escrito

La lección de la Fase 6 es que los tests que **nombran** defienden borrados
concretos y no detectan nada nuevo. Así que el criterio *«un usuario puede
hacer/ver X desde la UI»* no se añade sólo a la plantilla: se mide en
`tests/test_fase9_camino_de_usuario.py`, en los **tres eslabones** de la cadena
—endpoint → proxy/cliente → componente montado—, porque romper cualquiera deja la
capacidad igual de inalcanzable. Las excepciones van con **motivo y fase dueña**
(como `HUERFANOS_TOLERADOS`), y hay un test que comprueba que esa lista es
**portante**: si una ruta desaparece o gana UI, la excusa caduca y la suite cae.
Verificado por mutación: desmontar `SliceControls` lo caza; quitar una entrada de
la allowlist, también.

**Medido hoy:** 62 rutas de backend, **10 sin consumidor** (todas declaradas: 6
son entradas de scripting que la Fase 11 hereda) · 48 proxies, **1 sin llamador**
(`/api/system-check`, que consume el orquestador Tauri, no un componente) · 62
componentes, **0 sin importador**.

#### Auditoría retroactiva de los gates F5–F8

| Fase | ¿Entregó algo que el usuario no puede ver ni hacer? | Resuelto aquí |
|---|---|---|
| **5** | **Sí.** `solver_path`, `bounded_solver_requested`, `bounded_solver_active`, `projected_solver_used`, `lambda_used`, `lambda_effective` aparecían en **0 archivos** del frontend — incluido el arreglo estrella de esa fase, distinguir el solver *pedido* del *usado* | ✅ panel «Solver realmente usado» |
| **6** | Sí, **por el otro lado**: 3 UIs escritas y nunca montadas (fue ella quien lo encontró) | ✅ montadas |
| **7** | **Sí.** `regularization_functional` y `solver_converged` sólo llegaban al JSON | ✅ panel «Funcional y convergencia» + aviso en el visor |
| **8** | **Sí.** `lsqr_converged`, el deber que dejó nombrado | ✅ mismo panel |

Cuatro de cuatro. No es casualidad: es la propiedad estructural que la auditoría
ya había señalado (*«la disciplina de honestidad está implementada en la frontera
del backend y sistemáticamente no cruza al frontend»*), y es exactamente lo que el
guard nuevo impide que se repita.

#### Lo que queda fuera, a propósito y con nombre

* **`check_voxel_budget` no tiene ningún llamador de producción**: el límite de
  vóxeles del tier `free` no lo comprueba ninguna inversión. El panel de licencia
  muestra el límite rotulado *«lo declara el token; hoy ninguna inversión lo
  comprueba»* en vez de prometer un tope que no existe. Cablearlo cambia conducta
  (puede bloquear corridas) y no es trabajo de una fase de interfaz.
* **`TQ_LICENSE` (entorno) tiene prioridad sobre el archivo** que escribe
  `/license/activate`: activar desde la UI puede quedar anulado en silencio. No se
  cambia la precedencia —es una decisión de producto—; el panel **avisa** cuando
  `source === "env"`.
* **El ZIP de diagnóstico se escribe en `TMP_DIR` y nunca se borra.** Registrado,
  no arreglado: es política de retención, no interfaz.
* **`GET /diagnostics/manifest` y los 4 endpoints hermanos no declaran
  `response_model`**, así que su esquema OpenAPI va vacío. Es materia de la
  **Fase 10** (contratos tipados), que es la que va a generar tipos desde OpenAPI.

---

---

## FASE 10 — Contratos tipados y domar `PrepPanel` · **M** · 🟠 P1

*(antes «Fase J» — renumerada para que el rotulo sea el orden de ejecucion.)*

*(Fase nueva, derivada de H-16.)*

**Objetivo.** Eliminar la clase entera de bugs por divergencia de contratos, y hacer razonable el componente más valioso del producto.

**Justificación.** **[MEDIDO]** 40 nombres de tipo duplicados replicando esquemas Pydantic a mano (`BackendVoxelModel` ×4, `SniffReport` ×3, `BuildPackageConfig` ×3), y `PrepPanel.tsx` con 41 `useState` en 1.953 líneas. El primero es una bomba silenciosa (el backend cambia un campo y nada falla hasta que el usuario ve un dato vacío); el segundo es donde vive el paso que más valor genera.

**Diseño propuesto.**
1. **Generar tipos desde OpenAPI.** FastAPI ya publica el esquema; añadir `openapi-typescript` como paso de build y sustituir, al menos, los tipos del camino dorado. **Beneficio inmediato:** un cambio de contrato en el backend rompe la compilación del frontend en vez de romperse en producción.
2. **`PrepPanel`: 41 `useState` → `useReducer`** con un estado explícito y transiciones nombradas. No es estética: es lo que permite testear el panel por transiciones en vez de por combinaciones.
3. Extraer los sub-paneles (sniff, mapeo, correcciones, sondajes) a componentes con su propio estado acotado.

**Estrategia de pruebas.** Los 6 recorridos Playwright existentes son la red: deben pasar sin cambios antes y después. Añadir uno que ejercite el panel de preparación con un CSV sucio del corpus real.

**Criterios de aceptación.** `tsc --noEmit` limpio con los tipos generados; ningún componente con >12 `useState`; los recorridos Playwright verdes; ningún tipo del camino dorado declarado a mano.

**Riesgo.** Medio. **Dependencia:** iteración separada de frontend. **No combinar con la Fase 13** (undo/redo) — ambas tocan el estado; hacer la Fase 10 primero deja el terreno mucho mejor para la 13.

---

### ✅ CERRADA 2026-08-17 — lo que se midió, y en qué se equivocaba el plan

**Corrección a la justificación de esta fase.** El texto de arriba dice «40 nombres
de tipo duplicados replicando esquemas Pydantic a mano (`BackendVoxelModel` ×4,
`SniffReport` ×3, `BuildPackageConfig` ×3)». **Medido: son 13**, y dos de los tres
ejemplos son falsos — `SniffReport` y `BuildPackageConfig` están declarados **una
sola vez** en `frontendApi.ts` y re-importados; el contador de la auditoría tomaba
las líneas `type X,` de un bloque `import` por declaraciones. *(El auditor que
escribe esto cometió el mismo error de regex en su primera medición y lo detectó al
comprobarlo contra el archivo.)*

**Y el problema real era mayor que el que se contó.** La duplicación *dentro* del
frontend es menor; lo grave es que **44 de 65 rutas no declaraban esquema de
respuesta**, y entre ellas la cadena de ingesta entera (`analyze-columns`,
`parse-rows`, `enrich-package`, `build-package`, `load-package`). El paso (1) del
diseño —generar tipos desde OpenAPI— habría producido `unknown` justo en el camino
dorado. Por eso la fase empieza declarando contratos en el backend.

#### Los dos riesgos de declarar un contrato sobre un endpoint vivo

**[MEDIDO]** con FastAPI 0.135.3 / Pydantic 2.13.0, y muerden en direcciones
opuestas:

| Qué se hace | Qué le pasa al payload |
|---|---|
| `response_model` **estricto** | **BORRA en silencio** los campos no declarados. Sobre un endpoint que lleva años emitiéndolos, eso no documenta: destruye datos que el frontend consume. |
| `response_model` con `extra="allow"` | **INYECTA** los opcionales que el endpoint no emitió. Apareció `user_supplied_key: null` en 3 de las 4 features de conectividad, donde la clave no existía. |
| `extra="allow"` + `response_model_exclude_unset=True` | Payload **idéntico clave a clave**. Es lo que se usa, y hay test que lo comprueba llamando a los endpoints y comparando con el servicio. |

#### Tres hallazgos nuevos, ninguno en el plan

1. **`POST /license/activate` no devuelve `mode`; `GET /license/status` sí.** El
   frontend usaba **un solo tipo con `mode` obligatorio** para las dos respuestas:
   leer `.mode` tras activar da `undefined` y TypeScript no dice nada. No se cambia
   la conducta del backend —añadir un campo es decisión de producto—: se declaran
   dos contratos y el compilador pasa a saberlo.
2. **En un contrato de respuesta, un default es una promesa que nadie quiso hacer.**
   `Field(default_factory=list)` hace que OpenAPI marque el campo opcional; el tipo
   generado sale con `?` y el consumidor se llena de `?? []` para un caso que no
   puede ocurrir — y esa maraña esconde los sitios donde el campo **sí** puede
   faltar. Distinción hermana que Pydantic escribe igual: `Optional[str] = None`
   dice «puede FALTAR», `Optional[str]` dice «viene siempre, puede ser `null`».
   Efecto medido en el frontend al corregirlo: **25 errores de `tsc` → 1 → 0**.
3. **Cinco parámetros del campo geomagnético no tienen setter en ninguna parte.**
   `inclinationDeg`, `declinationDeg`, `fieldIntensityNt`, `suscMin` y `suscMax`
   viajan al motor magnético con los defaults del norte de Chile, mientras su
   comentario prometía que «el usuario puede ajustarlos según la región». No hay un
   solo input. `useState` lo escondía; al pasar a transiciones, el linter los delató
   como atajos sin llamador. **Queda dicho, no arreglado**: es interfaz de
   parámetros físicos y ponerla sin validación es peor que no tenerla.

#### El estado, y por qué no era estética

`PrepPanel` **41 → 0** `useState`; `PrepEnrichPanel` 17 → 0;
`GravityCorrectionWizard` 16 → 0; `HistorialView` 19 → 2. **Máximo del frontend
entero: 41 → 9.** El argumento no es el número: **H-29 fue un movimiento
multi-campo escrito a mano en dos sitios que divergieron** (al cambiar el CSV
magnético no se reseteaban los reconocimientos de riesgo). Ahora
`ARCHIVOS_CAMBIARON` es una transición en tres máquinas y cada una sabe qué de lo
suyo caduca. Lo mismo con el preset de densidad (existía «preset nuevo con bounds
viejos»), con el fallo al generar el paquete (mensaje de progreso y error
conviviendo) y con el paso 4 del asistente (podía mostrar la vista previa del mapeo
anterior). **El JSX no se reescribió**: atajos `set*` que despachan, igual que la
Fase 8 movió cuerpos sin tocar el texto.

#### Verificación por mutación (6 de 6)

quitar un campo del espejo del sniffer → rojo · quitar `exclude_unset` de
`/system/connectivity` → rojo · editar a mano el `.ts` generado → rojo · añadir un
campo al backend sin regenerar → rojo · superar el presupuesto de `useState` → rojo
· volver a copiar un contrato generado → rojo.

#### Lo que queda fuera, a propósito y con nombre

* **19 contratos siguen con cuerpo escrito a mano** en el frontend. Se intentó
  aliasarlos y `tsc` devolvió 20 errores de **una sola causa**: `default_factory` en
  los esquemas de convergencia, sondajes y correcciones marca opcionales campos que
  el servicio emite siempre. Arreglarlo bien exige tocar cinco esquemas más, con
  riesgo de HTTP 500 en rutas que **sí** validan. Revertido y declarado en
  `CONTRATOS_AUN_A_MANO`, con la lista impedida de crecer. **Dueña: Fase 11.**
* **`BlockModelResponse` del frontend no se genera, y es correcto**: es el tipo
  *normalizado* (el adaptador emite snake_case y camelCase para que el visor no
  tenga que saber de qué endpoint vino el modelo). Igual `BackendHealth`, que lo
  fabrica el proxy de Next. Generarlos sería declarar como contrato del backend algo
  que fabrica el cliente.
* **No se usó `openapi-typescript`**, que era lo que sugería el informe: añadir una
  dependencia npm necesita permiso expreso, el generador tiene que correr en el job
  de **backend** (donde vive la app que produce el esquema y donde no hay Node), y lo
  que hay que generar son ~30 tipos de un esquema que ya está en memoria.
* **No se fabricaron enumerados que el código no tiene.** `confidence` se emite como
  cadena libre; cerrarlo en Pydantic convertiría un valor inesperado en un **500 en
  plena ingesta**. Se transporta `string` y se estrecha al pintarlo.

**Gate:** 15/15 del guard nuevo · `tsc --noEmit` 0 · eslint 0 errores 0 warnings ·
`next build` OK · **28/28 Playwright** (25 previos + 3 del recorrido con CSV sucio) ·
guards de la Fase 9 en verde.

**GOTCHA que costó una investigación:** el `webServer` de Playwright corre
`npm run start` y **no reconstruye**. Comparar «con mis cambios» contra «sin mis
cambios» sin un `npm run build` en medio mide **el mismo bundle**: un fallo se
atribuyó a esta fase y la comparación era inválida.

---

---

## FASE 11 — API de scripting para el consultor experto · **S/M** · 🟠 P1

*(antes «Fase M» — renumerada para que el rotulo sea el orden de ejecucion.)*

*(Fase nueva, derivada del informe 04 §9F.3 y del 0% de "Automatización" del informe 03.)*

**Objetivo.** Que un consultor pueda invocar el pipeline desde Python sin pasar por la UI: procesar N surveys, re-generar reportes, automatizar el gabinete.

**Justificación.** El informe 04 llama a la interfaz de scripting *"una resolución de supervivencia, no una decisión cosmética"*: es lo que permite que el usuario construya lo vertical sin cargar al núcleo. **Y el usuario de TQ encaja en el perfil exacto**: experto, con poco soporte, que repite el mismo flujo muchas veces al año (`docs/02_PRODUCTO.md` §2). Para él, "procesa estos 12 surveys con la misma configuración" vale más que varias features de interfaz.

**[INFERENCIA] El coste es bajo y ése es el argumento.** El backend ya es Python, los servicios ya están factorizados y el flujo ya está descrito de punta a punta en el camino dorado. Falta un **punto de entrada estable y documentado**, no código nuevo: `terraquantum.run_inversion(package, config) -> RunResult`, `terraquantum.enrich(csv, ...)`, `terraquantum.export_report(run)`. Es envolver lo que existe con un contrato que se promete estable.

**Dependencias.** Se beneficia mucho de la Fase 8 (si la espina está partida, la API pública casi se escribe sola). Hacerla **después** de la Fase 8, o al menos después de la 7.

**Estrategia de pruebas.** La propia API se vuelve el mejor test de integración del proyecto: un script que corra los 4 datasets canónicos de punta a punta es simultáneamente el ejemplo de la documentación y un test E2E.

**Criterios de aceptación.** Un cuaderno o script de ~20 líneas reproduce el camino dorado completo sobre Laguna del Maule sin tocar la UI. La API tiene versión declarada y una promesa de estabilidad escrita.

**Riesgo.** Bajo, con una advertencia real: **publicar una API es un compromiso**. Conviene marcarla `v0` explícitamente hasta después de la Fase 8, para no congelar firmas que el refactor va a cambiar.

---

### ✅ CERRADA 2026-08-17 — cómo respondió las cuatro preguntas del gate

**Commits:** `84f42d9` backend (la API) · `f969702` backend (contratos: serialización) · `e4150d9` backend (cierre transitivo) · `75b70ad` frontend (15 alias) · proceso/docs (éste).

**1. ¿Qué puede hacer o ver un usuario que antes no podía?**
Procesar el pipeline entero desde Python sin abrir la interfaz — que en esta fase
*es* la superficie de usuario, no un subproducto. Medido con los dos ejemplos, que
la suite ejecuta: `examples/01` va del **CSV crudo de un Excel chileno** (191
estaciones reales de Laguna del Maule, con preámbulo, `;` y coma decimal) a modelo
3D, veredicto reconciliado, blanco recomendado, honestidad de profundidad, paquete
reproducible y ZIP de entrega, en ~20 líneas. `examples/02` recorre los canónicos.
Y `tq.batch([...12 surveys...], config=…)` es literalmente la frase con la que el
informe justificó la fase, con un test que corre doce.

**2. ¿Todo lo que la fase publica tiene consumidor?**
Sí, y de las dos deudas heredadas. De las 6 rutas que la Fase 9 toleró con «Dueña:
Fase 11», **5 tienen ahora consumidor de scripting** (`invert_field_csv`,
`invert_direct`, `estimate_depth`, `Run.profile`, `admin.create_api_key`) y un test
lo mide **sobre cadenas de código, no sobre texto** — los docstrings de la API citan
cada endpoint que envuelven, y contarlos sería el guard que se anula a sí mismo de
la Fase 6. La sexta, `/gravity-import/invert`, se toleraba «por compatibilidad de
scripts»: **medido, no hay ningún script de usuario**; la mantienen 13 tests de
contrato y el arnés `fase8_byte_identity.py`. La excusa nombraba al dueño
equivocado y queda contada. Además, `__all__` entero está ejercitado o declarado
con dónde.

**3. ¿Cada valor de cada enumerado nuevo está ejercitado?**
Sí, patrón de `test_fase1_literal_dispatch`: los tres valores de
`RATE_LIMIT_POLICIES` (`reset`/`wait`/`raise`) y los dos de `DATA_TYPES`, más el
rechazo del valor inválido. Un valor nuevo sin ejercitar rompe la suite.

**4. ¿El gate falla si se rompe lo que dice defender? — verificado por MUTACIÓN.**
**7 de 7 cazadas**: subir la versión a v1 sin escribir la promesa · meter un
default de física en la capa de scripting · exportar un símbolo sin ejercitarlo ·
dejar de usar una ruta declarada de scripting · perder la configuración del usuario
al hablar con el endpoint (divergencia H-29) · dejar de comprobar que el CSV existe
· fingir que el reset del limitador funciona contra un backend remoto.
**Dos de esas mutaciones encontraron el guard flojo antes que el usuario**: la de
la ruta pasaba porque un docstring que la nombra contaba como consumidor (se
cambió a análisis AST), y la de la divergencia porque el probe era inerte para esa
fixture (se añadió el control que demuestra que la comparación discrimina).

**Lo que NO se hizo, con nombre:** los tres defectos H-F11-1/2/3, los 20 modelos de
respuesta fuera del cierre de la deuda, y un modo silencioso para la API — **no se
promete** porque silenciar `structlog` no callaría los `print()` del motor
(`[F0.9 TENSOR MESH]`, `[FOCUSING]`, `[GPCG]`, `[BLOCK-MODEL-*]`) y una promesa a
medias es peor que ninguna.

---

---

## FASE 12 — OMF: dejar de ser una isla · **M** · 🟡 P2

*(antes «Fase E» — renumerada para que el rotulo sea el orden de ejecucion.)*

**Objetivo.** Exportar e importar Open Mining Format.

**Justificación.** Informes 02 §9 y 11 §4.6. Es el formato con el que el consultor entrega a una minera con Vulcan/Leapfrog. Sin él, el resultado de TQ muere en TQ. **Impacto comercial desproporcionado al esfuerzo técnico.**

**Diseño.** `services/omf_export_service.py` sobre la librería `omf` (evaluar licencia antes de añadir dependencia — regla del repo: pedir permiso). Volumen de bloques + superficies de isosuperficie + trazas de sondaje.

**Criterios de aceptación.** Un archivo OMF generado por TQ abre correctamente en un visor OMF de terceros, con geometría y atributos íntegros.

**Riesgo.** Bajo. **Dependencia nueva: requiere autorización explícita.**

### ✅ EJECUTADA — 2026-08-18

Dependencia **autorizada por el usuario**: `omf==1.0.1` (MIT). Ejecutada en dos
iteraciones (backend / frontend) por la regla del repo. Documento:
`docs/09_OMF_INTEROPERABILIDAD.md`. Gate: **16/16** de la suite nueva · guards de
las Fases 1, 3, 5, 9 y 10 en verde · `deps_closure` OK · `ast_budgets` OK ·
tipos generados al día · tsc **0** · eslint **0** · `next build` OK.

**La decisión de dependencia se tomó midiendo, no leyendo.** El plan pedía
«evaluar licencia antes de añadir». Se evaluaron tres candidatas y la licencia no
fue el único eje: `omf==1.0.1` es MIT en toda su cadena pero está **sin
mantenimiento desde 2019** y sólo publica sdist; el fork **vivo** `mira-omf`
3.4.0 (release de 2026-07, declara Python 3.12–3.14 y numpy 2.4.x, con wheel)
arrastra **`geoh5py`, que es LGPL-3.0-or-later** — inadmisible sin decisión
explícita en un producto que se distribuye como instalador firmado y se vende. Se
midió antes de instalar nada, cargando los paquetes desde `sys.path`: `omf` 1.0.1
**importa y hace round-trip completo** de los cuatro tipos de elemento en Python
3.14.4 con numpy 2.4.4.

#### El hallazgo de la fase: exportar a OMF obliga a mirar los ejes

El modelo interno **no** es (Este, Norte, Z): es `x_m`=Este, `y_m`=**PROFUNDIDAD
positiva hacia abajo**, `z_m`=Norte. La permutación correcta existe en el
repositorio —`gravity_import_service` la aplica al exportar UBC desde
`load-package`— pero **el bundle industrial no la aplica**:

- **H-F12-1** (🟠) — sobre una corrida real (`nx=20, ny=10, nz=20`), el
  `model.msh` que hay **en disco** dice `20 20 10` y el `model.msh` que el ZIP
  entrega al cliente dice `20 10 20`: **mismo nombre de fichero, misma corrida,
  Norte y profundidad intercambiados**. `_gslib_text` y `_aseg_gdf2_dat_text`
  comparten el defecto (emiten `(ix+0.5)*bs` etiquetado X/Y/Z sin permutar). No se
  arregla aquí —tocar el bundle industrial no es el alcance de esta fase y el
  repo prohíbe los refactors de oportunidad— y queda pinchado por un test de
  caracterización que se pondrá rojo el día que alguien lo corrija.

- **H-F12-2** (🟢, ajeno) — la especificación de GMG dice «Ordering increases U
  first, then V, then W», pero **`omfvista` lee las celdas transpuestas**
  (`np.reshape(arr, shp)` en orden C y luego `flatten("F")`). TerraQuantum escribe
  según la ESPECIFICACIÓN; queda test que deja constancia ejecutable de la
  discrepancia para que nadie «corrija» el exportador al ver el modelo raro en ese
  lector.

- **H-F12-3** (🟠, ajeno) — `omf.OMFReader`, si recibe una RUTA, **no cierra
  nunca** el descriptor (sólo su `__del__`). En Windows —el sistema del producto—
  eso hace fallar el borrado del temporal con `PermissionError [WinError 32]` y
  convertía un 422 limpio («esto no es un OMF») en un 500. Mitigado pasando un
  descriptor propio; hay test de regresión.

#### Lo que NO se inventa, medido en disco

Georreferenciar exige **dos** cosas a la vez (`absolute_origin` en la corrida y
CRS proyectado en `project_meta.json`): **25 de 105 proyectos** las cumplen; el
resto sale en metros locales **y el fichero lo dice**. No hay datum vertical en
todo el repositorio, así que el eje Z se declara como profundidad bajo la
superficie local, no cota. La corrida **conjunta** escribe una tabla dispersa sin
`ix/iy/iz` ni `inputs.json` (**493 corridas** en disco): se rechaza con 422 en vez
de inferir una malla. Y los atributos se curan **midiendo la propia corrida**:
`grade` es NaN en el 100 % de las celdas y `rho`/`density`/`density_t_m3` son bit
a bit el mismo array — publicarlos habría entregado una ley falsa y tres copias.

#### Las cuatro preguntas del gate

1. **¿Qué puede hacer un usuario que antes no podía?** Descargar la corrida en
   OMF (botón nuevo en el panel de exportación del visor 3D) y **cargar sondajes
   desde un OMF de terceros** (el panel de sondajes ahora acepta `.omf`), con el
   inventario de lo que traía el fichero a la vista.
2. **¿Todo lo que publica tiene consumidor?** Sí, medido:
   `test_fase9_camino_de_usuario` cazó `/borehole/import-omf` sin consumidor y se
   cableó (no se toleró). Cero excepciones nuevas.
3. **¿Cada enumerado nuevo ejercitado?** No se introdujo ningún `Literal` nuevo;
   `test_fase1_literal_dispatch` sigue verde.
4. **¿El gate falla si se rompe lo que dice defender?** Verificado por mutación:
   la comparación celda a celda se prueba contra valores alterados, y la
   permutación contra la mutación más plausible (olvidar el volteo vertical).

**Criterio de aceptación: parcialmente cumplido, y se dice.** No se ha abierto el
fichero en un visor de terceros — no es automatizable en CI y Leapfrog/Vulcan no
están disponibles. Lo verificado es el **mapeo** (geometría celda a celda,
orden según especificación, cabecera parseada a mano sin el lector de `omf`,
ida y vuelta exacta de sondajes). Pendiente para v1 en `docs/09` §7.

---

---

## FASE 13 — Undo/redo y densidad de UX experta · **L** · 🟡 P2

*(antes «Fase F» — renumerada para que el rotulo sea el orden de ejecucion.)*

**Objetivo.** Command pattern sobre las mutaciones del store + atajos + persistencia de layout.

**Justificación.** Informe 03 Mód. 8. **El coste de añadirlo crece con el tiempo**: cada mutación nueva de estado que se escribe sin él es deuda que habrá que reescribir.

**Diseño.** Middleware de Zustand que registre comandos inversibles para las acciones del usuario (no para datos derivados del backend). Empezar por las mutaciones del panel de preparación y de la vista 3D.

**Criterios de aceptación.** Ctrl+Z/Ctrl+Y en las acciones de preparación y visualización; el historial no crece sin límite; no interfiere con corridas en curso.

**Riesgo.** Medio: toca el store central. **No combinar con la Fase 8.**

---

---

## FASE 14 — Cablear el modelamiento implícito · **M** · 🟢 P3

*(antes «Fase G» — renumerada para que el rotulo sea el orden de ejecucion.)*

**Objetivo.** Que `implicit_modeling.py` (RBF/HRBF) llegue al usuario.

**Justificación.** Es la pieza construida-sin-cablear de mayor valor. Los tres informes geológicos coinciden en que es el núcleo del modelamiento moderno. **Pero:** debe entrar como *restricción geométrica de la inversión* (informe 11 §6.1), no como competidor de Leapfrog en modelado geológico — eso está fuera del anti-scope declarado.

**Criterios de aceptación.** Un contacto geológico mapeado por el usuario acota la inversión y se **mide** la mejora contra verdad conocida. Si no mejora, se documenta y no se promete (regla de oro del proyecto).

**Riesgo.** Medio. Es física nueva en el camino crítico: exige el mismo rigor de medición que la Fase 4.

### ✅ EJECUTADA — 2026-08-21

**Cierra ABRIENDO, y por poco no lo hace.** Medida con el cableado que había, la respuesta era la de la Fase 4: **no mejora**. La fase estuvo escrita y cerrada con ese veredicto. Lo que la cambió fue preguntarse si fallaba la idea o el **cableado** — y era el cableado: moviendo el `m_ref` al término donde Li & Oldenburg 1999 lo pone, el mismo prior, en el mismo mundo y con las mismas 25 semillas, **gana 25 de 25 en las cuatro métricas**, y la geología falsa pasa a ser el peor brazo de todos. La lección de proceso es esa: *«el parámetro no sirve» y «el parámetro no está donde debería» dan el mismo número, y sólo la segunda se arregla.*

**Medir antes de ejecutar volvió a cambiar la fase.** El plan decía «cablear `implicit_modeling.py`», dando por hecho que estaba desconectado. No lo estaba: la Fase 7.2 ya había cableado φ → `m_ref` en `services/geophysics_service.py:1779` (`_build_implicit_geology_reference`), con su llamada en `:3008`, su reporte en `:4957`, su esquema (`ImplicitGeologyParams`, `schemas/geophysics_schema.py:314`) y su suite (`tests/test_fase7_wiring.py`). Lo que faltaba era **el interruptor**: `implicit_geology` no estaba en la allowlist `_CONFIG_DEFAULTS` de `services/csv_package_service.py`, y `merge_config` **descarta en silencio toda clave desconocida** — así que un paquete que lo pidiera lo perdía sin un aviso. Los contactos litológicos, en cambio, **ya viajaban enteros** (`frontendApi.ts` los conserva en `boreholes_json`, `csv_package_service` los serializa al bloque `#BOREHOLES` sin allowlist y `gravity_import_api` los reconstruye). Es decir: la geología del usuario llegaba al motor desde antes; lo que no había era forma de encenderla.

**El hecho que gobierna toda la fase, y que no estaba escrito en ninguna parte.** El prior entra **únicamente** en el término de SUAVIDAD — `d_reg = λ_spatial · (L · m_ref)`, `exploration/gravimetry.py:2374` — y **no** en el de smallness, cuyo RHS es cero salvo en celdas ancladas por sondaje (`:2412`). Y `L` es un Laplaciano de grafo (`L = W − D`, `:1288`), así que **`L·1 = 0` EXACTO** (medido: `max|L·1| = 0.0` en malla uniforme, `4,2e-17` en no-uniforme). De ahí salen tres consecuencias que la API contradecía:

1. **Un `m_ref` espacialmente constante es exactamente inerte.** Si φ clasifica el 0 % o el 100 % de la malla como una sola unidad, la inversión sale **byte-idéntica** a no haber pedido prior — y el reporte decía `enabled: true` igual. Ahora se declara (`inert_no_contrast`) y se avisa.
2. **`target_density_t_m3` y `host_density_t_m3` no son dos perillas independientes: sólo actúa su DIFERENCIA.** Desplazar ambas por igual deja el `m_ref` desplazado por una constante, que el Laplaciano anula. El formulario lo dice y muestra el Δ.
3. **El prior es genuinamente GEOMÉTRICO** — sólo actúa en la curvatura del contacto, no fija densidades. Eso es exactamente lo que el plan pedía («restricción geométrica, no competidor de Leapfrog»), y conviene que esté escrito porque el docstring citaba a Li & Oldenburg 1999, cuyo `m_ref` actúa por el smallness.

**🟠 EL HALLAZGO DE LA FASE: con contactos a una sola profundidad, el HRBF degenera a un plano infinito.** Con un sondaje vertical y contacto a 90 m, los pesos RBF salen **~1e-15** y el campo queda en su deriva polinómica, φ = 2·ỹ: una rampa lineal en profundidad. Consecuencia medida: **φ ≥ 0 en el 85 % de la malla** (6.800 de 8.000 celdas), hasta **403 m** del único collar, sobre una malla cuya semidiagonal es 424 m. Con TRES sondajes cuyo contacto está a la misma profundidad, φ es **idéntico** (`max|Δφ| = 2,5e-13`): triplicar el dato no cambia nada. Y el campo sólo deja de degenerar cuando los contactos fijan curvatura — un cuerpo acotado arriba y abajo baja al 42,9 %, y con cuatro pozos estériles alrededor al 30,1 %. **El modelo implícito no tiene noción de «sin dato no afirmo»: extrapola la clasificación a toda la malla, siempre.** Nada de esto se veía: ahora el reporte publica `degenerate_planar_field`, `target_volume_fraction`, `extrapolation_max_m` y `n_boreholes`, y el panel del visor los pinta con sus avisos.

**LA MEDICIÓN, Y SU RESPUESTA.** Instrumento: `scripts/validation/f14_implicit_geology_experiment.py` (declarado **diagnóstico**, no puerta, en `GATES.json`: su respuesta puede ser legítimamente «no mejora»). Mundo: el dique inclinado a 60° de `tests/test_benchmark_dipping_dike.py` — elegido porque **el propio docstring de ese benchmark declara que el buzamiento NO es recuperable desde gravimetría de superficie** (no-unicidad de Skeels 1947). Si una restricción geométrica sirve, tiene que servir ahí. Anti-inverse-crime real: el dato se genera en malla refinada ×3 (54.432 celdas) y se invierte en la gruesa (2.016); discrepancia fina-vs-gruesa **4,08 % del pico**, el doble del ruido añadido (2 %). Cada pozo se «loguea» leyendo la verdad a lo largo de su vertical. **25 realizaciones de ruido, pareadas** (misma semilla = mismo ruido en todos los brazos), porque está medido en este repositorio que el motor es bimodal frente al ruido.

**El brazo de control es lo que hace honesta la medición**, y su primera versión estaba rota: al reflejar el dique sobre el eje equivocado los pozos no lo cortaban, todos los tramos salían «caja», φ < 0 en toda la malla y —por el hallazgo (1)— **el control era exactamente inerte**, es decir idéntico al brazo base. Corregido (dique reflejado en x, que los mismos pozos cortan a profundidades en orden invertido) produce **233 celdas objetivo frente a las 234** del prior bueno: misma cantidad de prior, geometría opuesta.

| brazo (mediana de 25 semillas) | PR-AUC | IoU@vol | Dice@vol | r Pearson | err. centroide |
|---|---|---|---|---|---|
| base (sin prior) | **0,5412** | **0,3895** | **0,5606** | 0,5128 | 46,5 m |
| 1 sondaje | 0,2468 | 0,1946 | 0,3258 | 0,3354 | 56,2 m |
| 3 sondajes | 0,4318 | 0,3608 | 0,5303 | **0,5210** | 35,0 m |
| 3 sondajes + 2 estériles | 0,4633 | 0,3401 | 0,5076 | **0,5357** | 41,3 m |
| **CONTROL (geología FALSA)** | 0,2513 | 0,2453 | 0,3939 | 0,3064 | **48,4 m** |

Pareado contra `base`: con 3 sondajes el prior **pierde** en PR-AUC (0/25 semillas), IoU (2/25) y Dice (2/25); sólo empata-gana en Pearson (15/25, Δ = +0,011). Con **un** sondaje pierde **0/25 en todo**. **Y el error de centroide MEJORA también con la geología falsa (14/25)** — el «espejismo del centroide» que este repositorio ya había medido en otro contexto, reproducido aquí: es la métrica que hay que descartar como evidencia, y por eso el instrumento lo hace explícitamente (`METRICAS_QUE_DECIDEN`).

**Primer veredicto: el prior geológico implícito, TAL COMO ESTABA CABLEADO, NO mejora la recuperación.** Y ahí la fase pudo haber cerrado —como la 4— si no se hubiera hecho la pregunta siguiente.

**🔴 LA PREGUNTA QUE CAMBIÓ EL RESULTADO: ¿falla la idea, o falla el cableado?** Ese número admite dos lecturas, y separarlas es barato. `m_ref` en la suavidad empuja la *rugosidad* mientras el smallness sigue tirando de cada celda hacia `base_density`, es decir **en contra del prior**. Li & Oldenburg 1999 —a quien el propio docstring cita— pone `m_ref` en el **smallness**. La alternativa resultó medible **sin tocar el motor**, por el canal de producción `extra_reg_blocks` (el mismo que usan PGI y cross-gradient: bloque `√α·I` con RHS `√α·m_ref`). El resultado, con el MISMO mundo, el MISMO anti-inverse-crime y las MISMAS 25 semillas pareadas, no es un matiz:

| brazo (mediana, 25 semillas) | PR-AUC | IoU@vol | Dice@vol | r Pearson |
|---|---|---|---|---|
| base (sin prior) | 0,5412 | 0,3895 | 0,5606 | 0,5128 |
| suavidad (cableado histórico) | 0,4318 **(0/25)** | 0,3608 (2/25) | 0,5303 (2/25) | 0,5210 (15/25) |
| **smallness** | **0,7805 (25/25)** | **0,6098 (25/25)** | **0,7576 (25/25)** | **0,7802 (25/25)** |
| smallness, densidad ×2 mal | 0,8323 (25/25) | 0,6923 (25/25) | 0,8182 (25/25) | 0,8250 (25/25) |
| smallness, densidad ×0,5 mal | 0,6952 (25/25) | 0,6098 (25/25) | 0,7576 (25/25) | 0,7269 (25/25) |
| **CONTROL geología FALSA** | **0,1606 (0/25)** | 0,2222 (0/25) | 0,3636 (0/25) | 0,2856 (0/25) |

**Veredicto final: la idea sirve; el cableado era el que no servía.** Por el smallness el prior gana **25 de 25 semillas en las cuatro métricas** (PR-AUC +0,250; IoU +0,228), y —lo que hace creíble el mecanismo— **la geología FALSA pasa a ser el PEOR brazo de todos** (0/25, PR-AUC −0,382): el término no premia «tener un prior», premia **acertar la geometría**. El brazo que más importaba para el producto es el tercero y el cuarto: **el usuario no tiene que acertar la densidad**. Equivocarla al doble o a la mitad sigue ganando 25/25, porque lo que transporta la información es *dónde* está el contacto, no *cuánto* contrasta.

**Por eso el default es `binding="smallness"`, y por eso ese cambio de default NO cambia el resultado de nadie:** antes de esta fase **ningún usuario podía activar la geología implícita** —la clave se descartaba en la allowlist—, así que no hay una sola corrida histórica con este prior encendido. Elegir el default de un interruptor que se estrena no es tocar el camino dorado. El cableado histórico se conserva íntegro y accesible como `binding="smoothness"`, con `α = 0` → el solver no apila el bloque → byte-idéntico a la Fase 7.2, y hay test que lo comprueba (`test_alpha_cero_es_byte_identico_a_no_pedir_el_binding_nuevo`).

**Y el cambio destapó un acoplamiento que habría corrompido el DOI en silencio.** La «inversión 1» del índice DOI **no se recalcula: ES la corrida principal** (`m1 = est_density`). Si la pass-1 lleva el bloque de smallness y la pass-2 no, la diferencia `m1 − m2` mezcla el desplazamiento de referencia —lo único que el DOI quiere medir— con un cambio de funcional, e infla el índice sin que nada avise. La pass-2 recibe el mismo `geo_prior_alpha`. *(Encontrado leyendo el sitio de llamada al cablearlo, no por un test: queda dicho.)*

**El wrapper cobró su peaje otra vez.** `_run_lsqr_with_heartbeat` es paso obligatorio del camino de producción, y un parámetro que no se declara ahí llega al motor por el camino directo (tests) y **no** por el del usuario. Es exactamente el tropiezo que este repositorio ya pagó con `anchor_mode` (Fase 2). Aquí lo delató la suite de la Fase 11 poniéndose roja con `unexpected keyword argument 'geo_prior_alpha'` en `/v2/gravity-import/load-package` — es decir, el guard que la Fase 11 dejó **defendió el camino del usuario**, que es para lo que se escribió.

**Lo que este resultado NO dice, y conviene fijarlo antes de que alguien lo cite de más.** Un mundo (dique inclinado a 60°), una λ, una malla, tres sondajes que **sí** cortan el cuerpo, y una geología «verdadera» leída de la verdad. No está medido en: cuerpos compactos, geología parcialmente equivocada (el control es equivocada *del todo*), sondajes que no llegan al objetivo, magnetometría ni inversión conjunta. La Fase 4 necesitó 3.450 inversiones para cerrar una pregunta de este tipo; aquí hay **150**. Lo que sí está establecido con esas 150 es la **dirección** y su **signo de control**, y es suficiente para elegir el default de un interruptor nuevo — no para prometerle a un cliente un porcentaje de mejora.

**Y el binding nuevo además CUESTA MENOS, que es lo contrario de lo que supuse.** Al ver el barrido tardar más di por hecho que el bloque extra —n_active filas más en el sistema aumentado— encarecía el solve, y estuve a punto de escribirlo como caveat del default. Medido sobre el mismo dique: **sin prior 30,3 s · suavidad 32,8 s · smallness 13,2 s**. Es **2,3× más rápido**, y tiene sentido: `α·I` es un bloque perfectamente condicionado, así que regulariza el sistema aumentado y el GPCG converge en menos iteraciones — un término de Tikhonov *mejora* el número de condición, no lo empeora. La lentitud que había observado era **contención de la máquina** (el repositorio vive en OneDrive y el proceso estaba recibiendo ~13 % de un núcleo), no el álgebra. Queda anotado como lo que es: **una medición de reloj de pared bajo carga no es una medición de coste**, y por poco entra al documento como si lo fuera.

**Tres colisiones medidas, ninguna con guarda antes de esta fase.** `m_ref` es un canal único multiplexado por tres productores con precedencia fija y no declarada: el anclaje por sondajes **pisa celda a celda** (`gravimetry.py:2369`) y en modo `hard` elimina la celda del sistema; el bloque PGI tira de la magnitud en otro término a la vez; y `lithology_hard_constraint` puede dejar `target_density_t_m3` fuera de la caja KKT y por tanto inalcanzable. La peor es la cuarta: **un intervalo con litología pero SIN densidad medida —que es justo el input que este prior exige— no entra al array de anclaje**, así que `enable_depth_prior` encuentra `boreholes_arr is None` y fuerza `anchor_mode="hard"`, que ancla a `base_density` y borra el prior. Esa se avisa ahora; las otras tres quedan **con nombre y sin arreglar**: arbitrarlas es tocar el camino dorado de todos los usuarios.

**Dos perillas que no actúan, declaradas en vez de disimuladas.** `target_std_t_m3` y `host_std_t_m3` se calculan (`implicit_modeling.py:435`) y **nunca se consumen**: el servicio sólo usa `prior.mean`. El esquema las llamaba «informativa» mientras la API las ofrecía como perillas; ahora el reporte publica `declared_std_is_inert` y hay test que comprueba que cambiarlas no mueve un solo valor. Además, `softness` ≥ 5 aplana el `m_ref` hasta un rango de 0,29 sobre 1,00 — camino de la inertidad del hallazgo (1); el deslizador se acota a 5 y lo dice.

**Las cuatro preguntas del gate.** (1) *¿Qué puede ver o hacer un usuario que antes no podía?* Encender el prior geológico desde Preparación → Avanzado → «Geología implícita», eligiendo entre **las litologías de sus propios sondajes** (no un catálogo inventado) con la densidad propuesta desde la tabla petrofísica del backend; y **ver en el visor** qué contacto acotó la inversión, qué fracción del volumen declaró objetivo, hasta qué distancia lo extrapoló, y si el campo degeneró o fue inerte. (2) *¿Todo lo que publica tiene consumidor?* Sí, y de paso **cierra una de sus dos deudas heredadas**: `/borehole/lithology-properties` sale de `RUTAS_SIN_UI_TOLERADAS` porque el formulario la lee de verdad (la tabla NO se duplica en TypeScript); `/borehole/desurvey` se **devuelve con motivo**: el modelamiento implícito consume pozos **verticales** (`from_boreholes` agrupa por `(x_m, z_m)`), así que cablear desurvey no habría hecho llegar la geología a nadie. (3) *¿Cada valor de cada enumerado nuevo está ejercitado?* La fase **no introduce ningún enumerado**: `ImplicitGeologyParams` ya existía y no tiene `Literal`. (4) *¿El gate falla si se rompe lo que dice defender?* **Cuatro mutaciones verificadas** — quitar la clave de la allowlist, volver inerte el detector de degeneración, borrar el aviso de colisión con el prior de profundidad, y dejar mudo el `except` que descarta un prior mal formado. **La cuarta destapó que mi propio guard era inerte**: miraba una ventana de 1.200 caracteres y el `elif` vecino la hacía pasar. Reescrito por AST —exige que *cada* manejador que descarta el prior escriba un warning— y re-mutado.

**Y un test de control fabricaba la deuda que otro test vigilaba.** El barrido de «Dueña: Fase N» de la Fase 13 recorre **todos** los `test_*.py`, así que las cadenas de muestra que escribí literales en mi propio test anti-inercia se contaban como declaraciones reales: el repositorio pasó a tener una «Dueña: Fase 14» que no existía. Lo destapó ese test poniéndose rojo, no una lectura. Las muestras se componen ahora en runtime.

**`test_fase13_undo_redo::test_control_el_barrido_de_duenas_encuentra_otras_fases` se actualizó, y conviene decir por qué no es maquillaje.** Exigía `"Fase 14" in encontradas` con el motivo «es la única del plan §10 que sigue abierta» — enunciado que deja de ser cierto justo cuando la Fase 14 cierra. Mantenerlo habría obligado a **dejar una deuda falsa para que un test pasara**. Se conserva la pregunta anti-vacuidad y se fija lo medido (`Fase 11: 7`, `Fase 13: 1`), de modo que una dueña nueva sin respaldo sigue rompiendo.

**Nota sobre `test_fase7_wiring::test_e2e_enabled_changes_model_and_reports`:** §10 lo registraba **en rojo** por un 9 % bajo su umbral (`max_diff = 9,10e-05` contra `1e-4`). Hoy **pasa** (2/2, 29 min 28 s). No se tocó ni el test ni el umbral: lo que hay que decir es que un test cuyo veredicto vive a un 9 % de su cota **no decide nada de forma estable** — es la fragilidad, no el resultado, lo que hay que anotar.

**Lo que NO entró, a propósito.** El motor magnético, el conjunto y el Octree **siguen ignorando** `implicit_geology` (el esquema ya lo declaraba); las orientaciones estructurales (`StructuralOrientation`) siguen sin forma de que el usuario las provea — cablearlas es una interfaz de medidas de dip/azimut, no un interruptor; las funciones de level-set (`evolve_level_set`, `reinitialize_sdf`) siguen sin llamador, que es el lado «geofísica → geología» del bucle y otra fase entera; y no se arbitran las tres colisiones de `m_ref`. **Gate:** **24/24** de la suite nueva · **4/4** recorridos Playwright de la fase · guards heredados en verde (Fase 1 **121/121** con los dos valores nuevos del enumerado clasificados, Fases 9/10/11/13) · `ast_budgets` / `deps_closure` / `compile_check` / `validation_inventory` / tipos generados OK · tsc **0** · eslint **0** · `next build` OK · **5 mutaciones verificadas** (allowlist, detector de degeneración, aviso de colisión, `except` mudo, y la propiedad `degenerado_a_plano`).

---

---

## Lo que NO recomiendo hacer

Esto es tan importante como el plan:

| Tentación del informe | Por qué NO |
|---|---|
| CUDA / GPU compute | Sin evidencia de estar limitado por cómputo en el rango que se vende. Lock-in NVIDIA contradice local-first en laptops |
| Lock-free / job system propio | El propio informe 01 admite "extrema complejidad de validación". Suicida para 1 persona |
| CGAL / predicados exactos / BRep | No hay booleanas CAD. Resuelve un problema que TQ no tiene |
| Clean Architecture + DDD + ECS completos | Sobreingeniería para un dominio único y un solo desarrollador |
| PINNs / kriging neuronal | Investigación, no producto. El proyecto ya lo rechazó con buen criterio |
| PostgreSQL/PostGIS | Contradice local-first, que es el foso comercial |
| Módulo de planificación minera | Competir con Datamine/Deswik. Anti-scope permanente |
| Reescribir el render con SVO+render graph | Solo si el producto sube un orden de magnitud en tamaño de malla |

---

# 11. CIERRE

**[OPINIÓN]** El riesgo real de este proyecto no es técnico. El motor funciona, está validado y su matemática resiste una auditoría. El riesgo es que **la complejidad acumulada en el camino crítico haga que el coste de cada mejora futura crezca hasta detener el desarrollo** — y que eso ocurra justo cuando lleguen los primeros usuarios reales y con ellos la presión de iterar rápido.

Las Fases 4, 8 y 3 atacan exactamente eso, y son baratas comparadas con lo que ya está construido.

Y una observación que no cabe en ninguna matriz: el hallazgo H-1 solo fue posible porque el proyecto había medido, documentado y publicado honestamente sus propias anomalías (`depth_beta` inerte, W_z-fix revertido, sesgo de profundidad dependiente del régimen). Un proyecto que hubiera escondido esos resultados incómodos habría hecho la causa raíz **invisible**. La honestidad epistémica que TerraQuantum practica como valor no es solo ética: es lo que hace el sistema auditable, y por tanto mejorable.

---

## 11.1 Qué queda por auditar (para la próxima sesión)

Esta auditoría se hizo en dos pasadas y **no está terminada**. Lo que sigue abierto, en orden de valor:

| Área | Estado | Por qué importa |
|---|---|---|
| ~~Empaque Tauri / sidecars~~ | ✅ **Auditado en 3ª pasada** (§9C.1-5, §9C.7) | Produjo los 2 hallazgos críticos del informe |
| ~~Tests: calidad real~~ | ✅ **Auditado en 3ª pasada** (§9C.6) | 66% de los "gates" no deciden nada; los oráculos que hay son genuinos |
| ~~Frontend en profundidad~~ | ✅ **Auditado en 6ª pasada** (§9E) | Produjo 5 hallazgos, 3 de ellos altos y de cara al usuario |
| ~~`geophysics_service`~~ | ✅ **Auditado en 5ª pasada** (§9D.2, §9D.2-bis) | Produjo H-27 y las 2 autocorrecciones |
| **`magnetometry.py`** | *Mayormente auditado* (§9-SEPTIES) | Solver principal y ensamblado leídos → H-33. **Sin leer: los solvers MVI, amplitud y tensor gradiente** (~800 LOC) |
| ~~Informe 04~~ | ✅ **Auditado en 7ª pasada** (§9-SEXIES) | Aportó la Fase 11 y el diseño de undo por deltas |
| ~~Informes 07, 12~~ | ✅ **Rechazo argumentado en 9ª pasada** (§9H.3) | El veto a CNN/U-Net es **por negocio (local-first), no técnico** — conviene que quede escrito |
| **Informe 13** | ✅ Leído por el auditor (§3.3, §6) | Es el más aplicable de los 13 |
| **Informe 06** | **Truncado en origen** | Regenerar el `.docx` antes de poder auditarlo |
| ~~UX comparada (informe 03)~~ | ✅ **Auditada en 9ª pasada** (§9H.2) | Con los 3 gaps que más costarían en demo y los 3 que serían sobreingeniería |
| ~~Solvers MVI / amplitud / tensor~~ | ✅ **Auditados en 11ª pasada** (§9-DECIES) | **La pasada más productiva**: produjo el 4º hallazgo crítico |

**Método recomendado para continuar:** los estudios instrumentados (§9-BIS) dieron más hallazgos por unidad de coste que la lectura asistida, porque el trabajo lo hace el análisis estático y no el modelo. Priorizar esa vía: un estudio de calidad de asserts, uno de complejidad del frontend, y uno de superficie de fallo del empaque.

---

*Fin del informe.*

*Artefactos de verificación reproducibles en `scratchpad/audit/`:*
- `verify_wz_cancel.py` — demostración numérica de H-1
- `metrics_backend.py` — métricas AST (LOC, args, complejidad ciclomática, anidamiento)
- `study_deadcode.py` — grafo de imports, símbolos huérfanos, inventario de variables de entorno
- `study_api_tests_deps.py` — endpoints vs consumidores, cobertura por módulo, dependencias
- `study_duplication.py` — duplicación por huella de tokens normalizada
- `extract_docx.py` — extracción de los 13 informes
- `maps/report_01..11.md` — árboles de conocimiento de los informes Deep Research
