# TerraQuantum — PLAN DE FASES 15 a 30

> **Revisión de cierre del plan §10** · abierto 2026-08-23 · actualizado **2026-08-26**
> Rama `fases-19-25-cierre`. Ninguna afirmación se apoya en documentación:
> todas citan `ruta:línea` o una medición reproducible.

> ### ESTADO — 2026-09-03
>
> **CERRADAS: 15 a 26.** Las dos de física salieron caras y
> valieron la pena: la **17** cambió el error de profundidad recuperada de
> **150,1 m a 14,7 m**, y la **18/19** midió que el motor magnético calculaba con
> `D_ef = 90° − D` — en Chile, **86° de desvío** y Pearson **r = −0,05** contra la
> anomalía real.
>
> Las dos del 27-ago fueron de honestidad, y **las dos encontraron que el defecto
> real no era el que la ficha describía**. La **20** buscaba avisar cuando se mueve
> `base_density`; midió que ese campo **no viaja desde la UI** y que lo que sí pasa
> es el simétrico: dos de los tres presets de litología imponen un piso de contraste
> **positivo** (magnetita +1,90 t/m³) que deja la roca caja fuera de la caja
> permitida y clava el **76,20 %** de las celdas al bound. La **21** cerró que el
> veredicto **mejoraba si se corrían menos diagnósticos**, y al cablear el techo al
> entregable destapó que el manifiesto del ZIP leía una clave que **nadie escribe**:
> el cliente recibía el QA de resolución con `pearson_r: null` y sin `status`.
>
> La **22** completó el patrón de las dos anteriores, y esta vez el defecto real no era
> más pequeño sino **más grande** que el de la ficha. ACAD-13 no vivía en un escritor
> sino en **tres** —el `.vtr`, el parquet del TargetingEngine y el `Density_Contrast` del
> **ASEG-GDF2**, cuyo fichero de definición *declaraba por escrito* «minus 2.6 g/cm3
> base»—, y dos de los tres viajan al cliente dentro del ZIP industrial. ACAD-12 no era un
> factor 1.000: la llamada de producción tampoco pasaba `block_size`, así que el volumen
> quedaba clavado en el de una celda de 10 m en las **1.034 de 2.089** corridas que usan
> otro dx. La decisión que el plan dejaba abierta —renombrar o multiplicar— se resolvió
> **midiendo**: cero consumidores en todo el monorepo, y un precedente del propio
> repositorio (`d424c7c`) que ya había resuelto el mismo defecto renombrando.
>
> La **23** encontró el mismo patrón de las tres anteriores por tercera vez, y otra vez
> en la dirección mala: la ficha de NUEVO-1 decía que a la conjunta «le falta el canal
> de avisos», y lo medido es que pasaba `topography_elevations=None` **fijo** a los dos
> motores — la misma corrida con y sin `sensor_elevations_masl` devolvía el modelo
> **idéntico bit a bit**, con el **15,93 %** del contraste recuperado dentro de celdas
> que son **aire**. Y el trabajo que el plan pedía —cablear `topography_run_warnings`—
> habría sido **decorativo**: ese aviso sólo se emite en `flat_fallback`, un estado que
> una ruta que nunca intenta interpolar no puede alcanzar.
>
> La **24** y la **25** cerraron los dos huecos de frontend, y las dos volvieron a
> encontrar el defecto **más grande** que la ficha: NUEVO-3 eran DOS capas —el validador
> local no reconocía ninguna de las 4 columnas que escribe su propio asistente, así que
> «Generar paquete» quedaba apagado y el CSV corregido **no podía llegar nunca** al
> backend—, y a la 25 le faltaban **5 entradas y un panel entero**.
>
> La **26** es la cuarta vez seguida que la ficha describe un defecto distinto del real, y
> la primera en que el trabajo que el plan pedía habría sido **insuficiente**: el techo a
> `MEDIUM` no lo causaba (sólo) la longitud de onda del tablero, sino **tres** causas
> independientes, y ésa es la menor —corregirla sola sube `pearson_r` de 0,116 a 0,247,
> con el PASS en 0,60. Las otras dos: el examen **puntúa profundidades que ningún survey
> gravimétrico resuelve** (el mismo tablero, puntuado en la banda somera con bloques
> grandes, saca **0,704**) y **califica a un solver distinto del que produce el modelo**
> (con el mismo dato, PR-AUC 0,04 donde producción da 1,000). El diagnóstico nuevo pasa de
> ρ = **+0,073** a **+0,87** contra PR-AUC, y de propina cierra la otra mitad del hallazgo
> —distinguir la corrida de 5,6 m de la de 285,5 m dentro del **mismo** régimen— con un
> dato que el producto ya calculaba y no miraba.
>
> **PLAN COMPLETO: 15 a 30, las dieciséis cerradas.** *(27, 28, 29 y 30 el 03-sep y el
> 06-sep.)*
>
> La **30** —la última— levantó el techo a `HIGH`, y lo primero que midió fue que **el
> trabajo que pedía su propia ficha no cambiaba nada**: quitar `high_hold_pending_fase30`
> dejaba **0 de 75** veredictos distintos, porque `priority_class` capaba a MEDIUM **las 44
> de 44** corridas MEDIUM —incluidas las de PR-AUC 1,000 y 11 m de error—. El techo eran
> **tres** cosas y la única declarada era la inerte. `HIGH` ya se alcanza
> (**24 %** de 150 corridas) y ya no se concede por ausencia de defectos: hay
> que **sellarlo**. Cuadrante SOBRECONFIADO: **0**, con el peor `HIGH` a
> 164,9 m. Mutación **12/12**.
>
> La **29** cerró el margen sin cuantificar, y lo primero que midió fue a sí misma: sus 14
> verificadores en paralelo **murieron por límite de sesión, los 14** — la tercera vez que
> pasa en este repositorio, así que el trabajo se hizo a mano. Los gates **defienden**
> (**15 de 16** mutaciones cazadas, y la que escapó destapó que el gate de duplicación
> cuenta huellas únicas), pero **152 pruebas escritas como gate no las ejecuta nadie** —
> incluidos los gates de aceptación **completos** de las Fases 11 y 14—. Y los dos
> hallazgos numéricos que el expediente académico declaraba «nunca medidos» ya tienen
> número: **ACAD-4 es real** (−2,7 % de amplitud bajo la topografía, 3/3 semillas) **y no
> cuesta targeting**; **ACAD-3 no se sostiene** — el operador de cuarto orden no
> sobre-suaviza, y lo que hay que corregir es la **cita**, no el operador.
>
> **Fases nuevas 20, 21, 26 y 30**, añadidas el 26-ago tras revisar una auditoría
> delta externa. Ojo: **los dos «CRÍTICO» que esa delta proponía atacar primero no
> se sostienen como los plantea**, y el desmentido está en tu propio repo —
> `validation/HALLAZGO_2026-08-06_bound_por_defecto.md` (que **retira por escrito**
> la recomendación sobre `density_min`) y
> `validation/HALLAZGO_2026-08-06_techo_medium.md` (que advierte que subir el techo
> a `HIGH` primero **sería peor que el estado actual**). Cada fase lo explica en su
> propio bloque.

---

## CÓMO USAR ESTE DOCUMENTO

En una sesión nueva de Claude Code, abierta en la raíz del proyecto:

```
Lee docs/10_PLAN_FASES_15_26.md y ejecuta la Fase 20 completa.
```

**El número de fase ES el orden de ejecución.** Empiezan en **15** porque las
Fases 1–14 son las del plan §10 de `docs/06_AUDITORIA_TECNICA_INTEGRAL.md` y ya
están cerradas. No digas «la Fase 5»: eso es la fase vieja (superficie de
configuración, cerrada el 2026-08-15). Di **«la Fase 15»**, «la Fase 16», etc.

Reglas que la sesión debe respetar (están en `.claude/CLAUDE.md`):
ninguna fase toca backend y frontend a la vez, no se instalan dependencias sin
permiso, y **ninguna fase se declara cerrada sin responder las 4 preguntas del
gate** (§10 de la auditoría). La 4ª es la que importa: *¿el gate falla si se
rompe lo que dice defender?* — verificado por **mutación**, no por lectura.

---

## 1. VEREDICTO

**No, no está todo listo — y lo que falta no es acabado, es corrección.**

Las 14 fases se ejecutaron y sus gates son reales. El problema es otro: las
auditorías se escribieron *antes* que las fases y **nunca se re-midieron contra
el código**. Al hacerlo aparecen cuatro defectos que las tablas dan por vivos y
que **lo siguen estando**, todos con la misma firma: el producto entrega un
número equivocado con cara de correcto. Dos afectan la física del resultado;
uno, el archivo que se le entrega al cliente.

Además, **189 commits** separan la rama de `main` (main está 0 por delante) y las
**Fases 12, 13 y 14 completas viven solo en el árbol de trabajo**.
*(Ambas cosas dejaron de ser ciertas el 2026-08-24: la **Fase 15** las commiteó en
10 commits y empujó la rama. La tabla de abajo es la del 08-23 y se conserva como
foto de partida; el estado vivo se lee en los **✅ EJECUTADA** de cada fase.)*

| | |
|---|---|
| Defectos que corrompen el resultado | **4** (hoy **3**: H-F11-1 cerrado por la Fase 16) |
| Defectos vivos confirmados (total) | **15** |
| Verificados como ya cerrados | **12** |
| Erratas encontradas en las auditorías | **2** |
| Frentes de verificación que no se corrieron | **11 de 18** |

### Cobertura honesta de esta revisión

Se lanzaron 18 verificadores en paralelo contra el código real, cada uno con un
escéptico asignado para intentar refutar lo que confirmara. **21 de 24 agentes
murieron por límite de sesión.** Sobrevivieron tres frentes (empaque, bugs de
confianza, motor magnético) y el resto se verificó a mano, priorizando lo que
más daño hace.

**Sí verificado:** corrección de terreno, convención de ejes magnética, ejes del
ZIP industrial, roles de columna en la ingesta, unidades de exportación, empaque
y updater, bugs de confianza del camino dorado, código muerto, dependencias,
constante de λ, CI de validación.

~~**NO verificado (queda como Fase 29** — este párrafo decía «Fase 26» y era una
errata: la renumeración del 26-ago movió ese trabajo a la 29, que es la que lo
describe en el §5**):** los gates de las 14 fases uno a uno, la
ejecución real de la suite, estructura y complejidad hoy, el operador de
suavidad de 4º orden y la frontera de Dirichlet, seguridad y red, listas de
tolerancia, higiene del repositorio, código muerto nuevo en el frontend.~~

**✅ VERIFICADO por la Fase 29 (2026-09-06).** Los once frentes de arriba están
medidos y la tabla §1.3 de `docs/06` re-escrita fila a fila con fecha y
`ruta:línea`. Y la Fase 29 volvió a tropezar con lo mismo que la dejó pendiente:
**sus 14 verificadores en paralelo murieron por límite de sesión, los 14** — tercera
vez en este repositorio (26 de 32 el 04-ago, 21 de 24 el 23-ago, 14 de 14 el 06-sep).
Aquí ya no es mala suerte: **la delegación masiva es un modo de fallo conocido de este
proyecto**, y lo que funciona es el trabajo secuencial. Queda **⬜ NO RE-MEDIDO** y se
dice: H-26 (las cuatro formulaciones de regularización, sin fase dueña) y la historia
de git de H-7 (el árbol sí está limpio).

---

## 2. LOS DEFECTOS QUE SIGUEN VIVOS

Ordenados por daño al usuario. Los cuatro primeros cambian el número que el
consultor entrega.

### ✅ H-F11-1 — Un CSV `X,Y,Z` entraba con los ejes cambiados, en silencio
**CERRADO por la Fase 16 el 2026-08-24.** Lo de abajo es el diagnóstico original.

`terraquantum-backend/services/gravity_import_service.py:154-156`

```python
_LOCAL_X_ALIASES: frozenset = frozenset({"x", "local_x", "coord_x"})
_LOCAL_Z_ALIASES: frozenset = frozenset({"z", "local_z", "coord_z"})
_LOCAL_Y_ALIASES: frozenset = frozenset({"y", "local_y", "coord_y"})
```

El slot `y_m` **es la profundidad** (convención interna: `y` = profundidad hacia
abajo). Con la cabecera más común del mundo — `X,Y,Z` = easting, northing,
cota — el **northing pasa a ser profundidad bajo superficie** y la **cota pasa a
ser northing**. No hay aviso: la inversión corre y entrega un modelo.

### 🔴 ACAD-1 — El campo geomagnético está rotado 90° en producción

Dos convenciones opuestas, y nada permuta en medio:

| Sitio | Qué dice | Ruta |
|---|---|---|
| Ingesta | `x_m slot = east/lon, z_m slot = north/lat` | `gravity_import_service.py:131` |
| Ingesta (UTM) | `easting→x_m slot, northing→z_m slot` | `gravity_import_service.py:339` |
| Motor magnético | `Convención de ejes del backend (idéntica a gravimetry): x=Norte, z=Este` | `magnetometry.py:31` |
| Motor magnético | `np.cos(I) * np.cos(D),   # x = Norte` | `magnetometry.py:92-97` |
| El empalme | `sensor_coords = np.array([[o.x_m, o.y_m, o.z_m] for o in obs])` — sin permutar | `geophysics_service.py:2107` |
| El empalme | `sensor_coords[:, [0, 2]],  # (x=Norte, z=Este)` | `geophysics_service.py:2125` |

La columna 0 contiene el **easting** y el motor la multiplica por `cos I·cos D`,
que es la componente **Norte** del campo.

**Por qué nadie lo vio, y son dos razones:**
1. **Gravimetría es invariante** — usa solo la componente vertical (`_nagy_prism_safe`),
   simétrica bajo el intercambio x↔z. El defecto es exclusivamente magnético.
2. **Los benchmarks son ciegos por partida doble** — DO-27 y Raglan son árticos
   (`cos I ≈ 0,11`, efecto mínimo) **y además no pasan por el importador**: los
   harness (`scripts/validation/ingest_do27.py:100`, `raglan_harness.py:104`)
   arman el frame a mano *con* la convención del motor, así que son consistentes
   pase lo que pase en producción. El caso de uso declarado es Chile,
   `cos I ≈ 0,87`, donde el efecto sería máximo.

> Nota: `exploration/gravimetry.py` **no declara ninguna convención de ejes**, así
> que la afirmación de `magnetometry.py:31` de ser «idéntica a gravimetry» no es
> verificable desde gravimetry.

> **MEDIDO por la Fase 18 (2026-08-25) — sigue VIVO, la Fase 19 lo corrige.**
> La consecuencia numérica ya no es una hipótesis: producción calcula con una
> **declinación efectiva `D_ef = 90° − D`** (identidad verificada a 10⁻¹³ nT), así
> que **no es una rotación de 90° sino una REFLEXIÓN sobre el azimut 45°** — con
> `D = 2°` el desvío es **86°**, y con `D = 45°` el defecto sería **exactamente
> invisible**. En Chile la anomalía predicha queda **incorrelada con la
> verdadera** (Pearson **r = −0,05**); por el camino de producción completo el
> error horizontal del blanco pasa de 30 m a **150 m** y el misfit de 1,0 % a
> **51,6 %**. En el Ártico los dos brazos son indistinguibles: índice de ceguera
> **√2·cos I·|sin D − cos D|** = 1,18 (Chile) vs 0,24 (Raglan) y 0,07 (DO-27).
> Detalle y decisión: `docs/11_CONVENCION_DE_EJES.md`.

### ✅ ACAD-0 — La corrección de terreno usaba el módulo, no la componente vertical

`terraquantum-backend/services/gravity_corrections_service.py:183`

```python
tc_contrib = _G_NEWTON * rho_kg_m3 * cell_area * np.abs(dh) / r_m ** 2
```

Calcula `G·ρ·A·|dh|/r²` — el **módulo** de la atracción de la masa puntual.
Falta el factor `|dh|/r` que proyecta sobre la vertical; la formulación clásica
de columna vertical da `≈ G·ρ·A·dh²/(2r³)`. La razón es `2r/|dh|` y **crece con
la distancia**, con radio por defecto de 22 km. Medido: **200× a 1 km con 10 m
de desnivel; 12× en el total** de un cono de 500 m — sobre una señal de 0,1–10 mGal.

**Está activa por defecto y entra en el dato que se invierte:**
- `api/gravity_import_api.py:691` → `apply_terrain: bool = Form(True)`
- `services/gravity_import_service.py:1895` → alimenta `g_corrected_mgal`
- `:1901` → `effective_observations = [GravityObservation(..., g=float(gc)*1e-5) ...]`

Mitigante: requiere que la descarga del DEM de OpenTopography tenga éxito; si
falla, se añade un warning y la TC se omite.

> **CERRADO por la Fase 17 (2026-08-25).** La fórmula es ahora la componente
> vertical de la columna en forma cerrada y estable, verificada contra el prisma
> exacto de Nagy y por mutación 4/4. Medido E2E sobre una sierra de 800 m de
> desnivel: la TC pasa de 67–117 mGal (absurdo) a 2,5–6,8 mGal, y el error de
> profundidad del cuerpo recuperado de 150,1 m a 14,7 m.

### 🟠 ACAD-1c — El ZIP industrial escribe UBC-GIF sin permutar ejes ni georreferencia

Hay **dos escritores del mismo formato** y solo uno permuta.

El de disco, correcto (`services/gravity_import_service.py:2121-2133`):
```python
_arr3d = _density_full.reshape((nx, ny, nz), order="F")   # (E, depth, N)
_arr_ubc = np.transpose(_arr3d, (0, 2, 1))[:, :, ::-1]    # (E, N, Z-up)
_ubc = export_core_to_ubc(..., nx=nx, ny=nz, nz=ny, ...)  # UBC: nE, nN, nZ
```

El del ZIP, crudo (`services/export_service.py:630-634`):
```python
def _ubc_msh_text(nx: int, ny: int, nz: int, bs: float) -> str:
    ...
    return f"{nx} {ny} {nz}\n0.00 0.00 0.00\n{dx}\n{dy}\n{dz}\n"
```

Para un modelo 20×10×20 las cabeceras salen `20 20 10` y `20 10 20`. Afecta
también al orden del `.den` (`_ubc_mod_text`, sin transponer ni invertir Z) y a
las coordenadas del `.gslib` (`_gslib_text`, que etiqueta `X_m/Y_m/Z_m` sobre
los índices internos). El origen es `0 0 0`: sin georreferencia.
**Invisible con malla cúbica** — y el ZIP es el artefacto de entrega al cliente.

### 🟠 Resto de defectos vivos

| ID | Qué pasa | Dónde |
|---|---|---|
| ✅ **NUEVO-1** *(cerrado por la Fase 23, 08-31)* | La **inversión conjunta** ignoraba la topografía por completo y su reporte no tenía el canal de avisos de la Fase 1. **Y era peor que «falta el aviso»:** `topography_elevations=None` fijo ⇒ la cota del CSV **no tocaba la física** (mismo modelo bit a bit con y sin ella; **15,93 %** del contraste recuperado en celdas de **aire**). Ahora la superficie llega a las dos físicas y los tres campos de honestidad viajan por el canal que el frontend ya pinta | `services/joint_inversion.py`, `services/geo_utils.py` |
| ✅ **NUEVO-2** *(cerrado por la Fase 24, 09-02)* | Cambiar de pestaña perdía el mapeo de columnas, los puntos Helmert, los sondajes y 25 parámetros. **Y era más:** «25» es exacto pero **5 de esos 25 no tienen control** (constantes disfrazadas), así que lo perdido de verdad eran **19**; y los que se evaporaban en total eran **61** campos en el núcleo montado. **La errata:** «los archivos sí sobreviven» sólo valía para el flujo CLÁSICO — el **PRINCIPAL** perdía el archivo entero. Dos consecuencias sin declarar: un survey magnético quedaba **invalidable** (`dataType` volvía a `gravity` con el fichero aún cargado) y ese fichero **seguía viajando invisible** en el paquete | `views/PreparacionView.tsx`, `store/useAppStore.ts` |
| ✅ **NUEVO-3** *(cerrado por la Fase 24, 09-02)* | El CSV corregido se descartaba al cambiar de pestaña y el paquete se rearmaba sobre el crudo. **Y era peor: eran DOS capas.** El validador local comparaba la cabecera **por igualdad** contra una lista que **no contenía ninguna de las cuatro columnas que el propio asistente escribe** ⇒ `can_invert: false` ⇒ «Validar» y «Generar paquete» **deshabilitados**: dentro de un mismo montaje el corregido **no podía llegar nunca** al backend, y el único modo de reactivar el botón era cambiar de pestaña, que lo reactivaba *destruyendo la corrección*. Además `allow_g_raw` cambiaba de `true` a `false`: el backend recibía otra **configuración**, no sólo otro fichero | `PrepPanel.tsx:193,1101,1202` |
| **H-36** | `resultIsStale` es una **lista a mano ya atrasada**: los parámetros de la Fase 14 no están, así que cambiarlos no marca el resultado como desactualizado. (La otra mitad, `modelRunKey`, sí es un invariante sólido) | `store/useAppStore.ts` |
| ✅ **ACAD-12** *(cerrado por la Fase 22, 08-27)* | `bulk_rock_mass_kg` **contenía toneladas** — factor 1.000. **Y era peor:** la llamada de producción no pasaba `block_size`, así que el volumen quedaba fijo en el de una celda de 10 m (**1.034 de 2.089** corridas usan otro dx) y un tope silencioso recortaba las grandes. Renombrada a `bulk_rock_mass_tonnes` — 0 consumidores medidos — con el dx y los índices reales | `exploration/gravimetry.py:4233,4248` |
| ✅ **ACAD-13** *(cerrado por la Fase 22, 08-27)* | La exportación calculaba el contraste contra el **literal 2.6**. Eran **TRES** escritores, no uno: el `.vtr`, el TargetingEngine y el **ASEG-GDF2** (entrega regulatoria AU/NZ), más la nota del reporte. Dos viajan al cliente en el ZIP | `export_service.py:31,212` **y `:947,973`** · `gravimetry.py:4213` · `geophysics_service.py:5128` |
| **NUEVO-9** *(abierto por la Fase 22, 08-27)* | El `config_hash` del manifiesto del ZIP (`_AUDIT_KEYS`) ignora `base_density`, `density_min` y `density_max`: dos corridas con roca caja distinta salen con el **mismo hash de auditoría**. Hay dos listas paralelas que sincronizar | `export_service.py:612`, `reporting/report_generator.py` |
| ✅ **H-20** *(cerrado por la Fase 28, 09-06)* | El endpoint apunta al remoto real y el aviso distingue **cinco** desenlaces con causa y acción propias, no el único alcanzable de antes. **Y la ficha se quedaba corta en dos sitios:** `TerraQuantum/terraquantum` no es un repositorio «inexistente» — `api.github.com/users/TerraQuantum` da **200** y es la cuenta de un **tercero real** (id 90737998); y el 404 llegaba al código como `ReleaseNotFound`, **perfectamente distinguible** de un fallo de red (`updater.rs:483-530`: un status no exitoso no guarda error), así que la información para no mentir ya estaba ahí y se tiraba. De propina, `check()` **no tenía tope de tiempo**: una red que acepta y calla dejaba la ventana en «Consultando…» para siempre, que es H-17 en otra ventana | `src-tauri/tauri.conf.json:34`, `lib.rs:952-1010` |
| ✅ **NUEVO-4** *(cerrado por la Fase 27, 09-03)* | El `.spec` recolectaba `[]` y seguía ⇒ el instalador salía sin OMF sin avisar. **Y la ficha señalaba el mecanismo equivocado:** `collect_submodules` **no lanza** cuando el paquete falta (`return []` con log DEBUG que `--log-level WARN` no imprime), así que propagar la excepción —lo que pedía el plan— no habría cambiado nada. Se comprueba el RESULTADO, y en **dos** formas: `[]` y `[pkg]` a secas. Medido con `omf` ausente: HEAD **no aborta** y empaqueta `['omf']` con **0 submódulos** (sanos son 10); ahora **exit 1 en 10 s** con el comando real. De propina: `email_validator` llevaba años recolectando `[]` sin estar instalado ni usarse, y los **121 submódulos de la app** dependían del *cwd* | `terraquantum_backend.spec` |
| **H-39** | Los kernels de **MVI y tensor siguen ignorando `near_field_mode='prism'`** y usan siempre dipolo. La auditoría lo marca `[HECHO]`: ahí significaba «leído», no «arreglado» | `exploration/magnetometry.py` |
| **H-34** | **Turbo sobrevive en la leyenda** de `MultiPhysicsControls`, describiendo colores que ya nadie pinta. Peor que antes: ahora la leyenda miente sobre lo que se ve | `componentes/.../MultiPhysicsControls.tsx:32,335` |
| ✅ **H-23** *(cerrado por la Fase 27, 09-03)* | Ya hay lockfile: `requirements.lock`, **105 paquetes** con el sha256 de **todos** los ficheros de cada versión, instalado con `--require-hashes` en la CI y comprobado en el build. Generado **sin dependencias nuevas** (`scripts/ci/gen_lockfile.py`, sólo stdlib) porque `pip-compile` habría exigido permiso. Verificado en Windows **y** Linux —conjunto idéntico, cero marcadores— y con control negativo (hashes corrompidos ⇒ pip rechaza). El intérprete ya se **resuelve** desde `.python-version` en vez de tomar el `python` del PATH, que aquí es 3.11.9 **sin los 105 paquetes** | `requirements.lock`, `scripts/build_desktop.ps1` |
| ✅ **NUEVO-5** *(cerrado por la Fase 27, 09-03)* | `six==1.17.0` pineada. La declaran `omf` (**sin especificador ninguno**) y `properties` (`>=1.7.3`). Además se añadió el invariante que faltaba: un test lee las dependencias de `omf` de sus metadatos y exige que **las cuatro** estén pineadas, para que la lista del comentario no vuelva a desincronizarse del código | `requirements.txt` |
| **NUEVO-6** | Tauri sirve en el **primer puerto libre 3000..3011** ⇒ `localStorage` se pierde solo, incluidas las preferencias y la clave del copiloto | `src-tauri/src/lib.rs` |
| **NUEVO-7** *(medido por la Fase 16, 08-24)* | El plan de mapeo publica `suggestions` —qué columna va en cada rol, deducido del RANGO de los valores— y **ningún `.tsx` la lee**: 0 consumidores. La UI abre el paso de mapeo (`PrepEnrichPanel.tsx:324` sí reacciona a `needsMapping`) pero muestra una lista de columnas desnuda mientras el backend ya sabe cuál es cuál. Desde Python sí se ve. Familia **H-10**; el guard de la Fase 9 no lo caza porque mide **rutas y componentes**, no **campos de una respuesta** | `types/backend-contracts.generated.ts:210` |

---

## 3. LO QUE SÍ QUEDÓ CERRADO DE VERDAD

Verificado en el código, no en el CHANGELOG.

- **H-2** — `solve_sparse_normal_equations` ya no se invoca, y
  `tests/test_fase6_limpieza_verificada.py:46` **falla si vuelve a aparecer**.
- **H-14** — `distributed` y `shapely` eliminadas, con fecha y motivo en el
  propio `requirements.txt`.
- **H-17/18/19** — Splash finito con causa en español, `[Reintentar]` y
  `[Ver registros]`; Job Object con `KILL_ON_JOB_CLOSE`; comprobación de
  **identidad** del puerto, no solo de que alguien escuche.
- **H-27** — El aviso de topografía plana llega al usuario extremo a extremo en las
  **tres** rutas. La conjunta se cerró en la **Fase 23** (08-31), y no sólo el aviso:
  también la topografía, que esa ruta descartaba en silencio.
- **H-28** — Cerrado **por invariante** (`modelRunKey`: el modelo lleva el sello
  de la corrida y la vista se niega a pintarlo si no coincide), que era la
  alternativa robusta de la Fase 1, no la barata.
- **H-29** — El reconocimiento de riesgo ya no sobrevive al cambio de archivo, y
  se validan **todos** los archivos del paquete.
- **H-37** — El modo `amplitude` fantasma, cerrado por **rechazo explícito** con
  error nombrado. Cierre legítimo, pero conviene saber que el usuario **perdió
  una opción de la UI**, no la ganó.
- **ACAD-14** — Las tarjetas económicas sin productor desaparecieron del
  frontend, coherente con el anti-scope permanente.

---

## 4. DOS ERRATAS DE LAS AUDITORÍAS

**No citar estas dos ante un profesor sin corregirlas antes.**

### ACAD-6 no se sostiene tal como está escrito

El expediente afirma que `PRECONDITIONED_OPERATING_LAMBDA = 0.1` contradice el
comentario que la explica, que supuestamente validaría λ≈3. En el sitio de la
constante (`services/geophysics_service.py:59-72`) el comentario dice **lo
contrario**: «el lambda óptimo para el benchmark es 0.1», «Pearson máximo en
lambda=0.1 (r=0.73)», «a lambda=3.0 el chi²=33 (sobre-regularización severa)».
Código y comentario coinciden.

Lo que sí hay ahí, escrito por el propio código, es una limitación distinta y
real: está calibrada en `n_active=256` sobre un sintético 8×4×8 y
**«no verificado a escala regional real»**. Ese es el hallazgo defendible.

### H-4 está medio cerrado, y el repositorio lo confesó por escrito

La CI ya define `TQ_RUN_VALIDATION: "1"`, pero solo para dos tests concretos
(`test_f9_physics_regression.py::test_synthetic_sphere_recovery` y
`test_depth_prior_service.py -m validation`). El comentario del workflow lo
admite: «el diseño de la fase pedía `pytest -m validation` entero. No estaba».

**El patrón importa más que el caso:** la tabla §1.3 de
`docs/06_AUDITORIA_TECNICA_INTEGRAL.md` **no se re-midió después de las 14
fases**. Marca como vivos hallazgos cerrados (H-2, H-14, H-17…) y como `[HECHO]`
hallazgos vivos (H-39). Para alguien que llegue nuevo, hoy desinforma.

---

## 5. EL PLAN

---

### FASE 15 (CERRADA) — Poner a salvo tres fases que solo existen en tu disco · **S** · 🔴 **P0** · *git*

**Por qué va primero.** No es deuda técnica, es riesgo de pérdida. 189 commits
separan la rama de `main` y las Fases 12, 13 y 14 no están en ningún commit.
Todo lo demás construye encima.

**Trabajo.**
1. Commitear las Fases 12, 13 y 14 **en tres commits separados**, respetando la
   separación backend/frontend.
2. Incluir `requirements.txt` y `terraquantum_backend.spec` en el commit de la
   Fase 12: la declaración de `omf==1.0.1` vive solo en el árbol, y **sin ella
   HEAD produce un instalador sin OMF**.
3. Verificar que `ci.yml` y los tests que nombra se commiteen juntos — hoy el
   workflow lista `test_fase13_undo_redo.py`, que no está versionado.
4. Decidir qué pasa con `Real-ESRGAN/`, `tools/`, los nueve `screen_*.png`,
   `postulacion_atrevete/` y los notebooks: `.gitignore` o fuera del repo.
5. Fusionar a `main`, o al menos empujar la rama.

**Gate.** `git status --porcelain` no lista nada del producto, y un `git clone`
limpio en otro directorio compila el backend y pasa la suite rápida.

#### ✅ EJECUTADA — 2026-08-24

**10 commits**, rama empujada (`9cdd8b0..552a00c`, sin `--force`), **199 por
delante de `main`**; `main` intacto por decisión explícita —fusionar metería ahí
los tres defectos que aún corrompen el resultado—. `git status --porcelain` y
`git diff HEAD` vacíos: el árbol quedó **byte-idéntico** a lo que había, que es
la prueba de que partir los commits no perdió nada.

**Estructura:** convención de la casa (`Fase N (backend)` / `(frontend)` /
`(proceso)`), y **los diez cumplen la regla de oro sin excepción** — incluido
partir la limpieza de READMEs en dos commits, uno de ellos de **un solo fichero
borrado**, porque una regla que se cumple «salvo cuando incomoda» deja de ser
comprobable. Dos ficheros (`PrepPanel.tsx`, `frontendApi.ts`) mezclaban fases y
se partieron **a nivel de línea** (bloques `difflib` + `git hash-object` +
`update-index`, sin tocar el árbol). `docs/06` **no** se pudo partir: la Fase 13
no tiene sección «EJECUTADA» propia y la línea «CERRADAS: 1 a 14» sólo es cierta
con las tres dentro — partirla exigía inventar frases de transición.

**Lo que apareció al medir el gate: DOS puertas de CI en rojo que nadie sabía.**
Las dos las causaba el trabajo sin commitear, así que HEAD habría entrado en rojo
el día que se commiteara sin más.
1. **El gate de H-22 castigaba la frase honesta.** Acusa a un script declarado
   `diagnostico` que la documentación cite en una línea que diga «gate»; la Fase
   14 escribió *«declarado diagnóstico, no puerta, en `GATES.json`»* y
   `GATES.json` en minúsculas **contiene la subcadena `gate`**. Se excluye el
   nombre del propio manifiesto antes de buscar la palabra. Mutación en las dos
   direcciones: una acusación legítima sigue fallando, y sigue fallando también
   cuando aparece en la misma línea que nombra `GATES.json`.
2. **El formulario plano de la Fase 8** llevaba rojo desde que la Fase 14 añadió
   `implicit_geology_json`. La lista congelada **no crece** —es la foto del
   contrato pre-Fase 8 y es lo que hace verificable la mitad «falta un campo»—;
   el campo nuevo va en `CAMPOS_ANADIDOS_DESPUES` con su fase dueña, más una
   tercera aserción contra declaraciones fantasma. Mutación 3/3.

**Y una trampa en el `.gitignore` de la limpieza del 08-23:** los patrones iban
**sin anclar**, y `*.ipynb` casa los **12 notebooks YA VERSIONADOS** de
`DO-27_Kimberlite/` y `Raglan_Magnetic/`. Hoy no se perdía nada (git no deja de
seguir un fichero ya seguido), pero el día que alguien añadiera un notebook de
benchmark desaparecería en silencio. Todos anclados con `/` y verificado con
`git check-ignore` en las dos direcciones.

**Gate medido:** clon limpio → compila **9 paquetes** · **5 guardas de CI** en
verde · suite rápida **266 passed / 2 skipped / 0 failed**. Y la **suite completa
`-m "not slow"`: 2601 passed, 5 skipped, 0 failed** (4 h 49 min). Los 2 skips de
la rápida son de entorno (`test_fase3_f9_no_evaluado.py:142`, no hay corrida viva
en la máquina), no fallos tapados.

---

### FASE 16 (CERRADA) — La ingesta deja de adivinar el rol de una columna · **S** · 🔴 **P0** · *backend* · H-F11-1

**Por qué va aquí.** Es el defecto más barato de arreglar y el que más usuarios
muerde. Va antes que los otros porque corrompe el dato **de entrada**: todo lo
que viene después hereda el error.

**Trabajo.**
1. Sacar `"y"` de `_LOCAL_Y_ALIASES` (`gravity_import_service.py:156`), o exigir
   confirmación explícita cuando `y` aparece junto a `x` y `z` sin columna de
   profundidad declarada.
2. Regla nueva: si las tres columnas son `x/y/z` desnudas, el rol de cada una
   **se pregunta**, nunca se asume. El mapeo manual ya existe — es cablearlo a
   este caso.
3. Auditar por el mismo criterio `_LOCAL_X_ALIASES` y `_LOCAL_Z_ALIASES`.

**Gate.** Un CSV con cabeceras `X,Y,Z` y valores de easting/northing/cota
chilenos: o se rechaza pidiendo el mapeo, o asigna los tres roles correctos.
El test debe **fallar** si alguien devuelve `"y"` a la lista de profundidad.

#### ✅ EJECUTADA — 2026-08-24

**Salida elegida: se PREGUNTA.** `tests/test_fase16_roles_de_columna.py`, 17
tests.

**Alcance medido antes de tocar nada, para saber a quién muerde:** de los **210
CSV del árbol**, la regla nueva bloquea **exactamente 3** — `DO27_Gravity_mGal`,
`DO27_Magnetic_TMI_nT` y `Raglan_Magnetic_TMI_nT`, es decir los tres ficheros
publicados con cabecera `X,Y,Z`, que son justamente los que se estaban
corrompiendo. Ninguna fixture de LdM, ni el `do27_gravity_LISTO_mini`, ni los
datos de prueba cambian de conducta.

**El punto 1 del plan, medido, no alcanzaba.** Quitar `"y"` de la lista —el
arreglo obvio— deja `x`→este ✔, `z`→**norte** ✘ (pero `z` es la cota) y el
northing **descartado**: se cambia una corrupción silenciosa por otra **peor de
ver**, porque desaparece el número absurdo (7e6 m de profundidad) que era lo
único que podía delatarla. Por eso el arreglo es el punto 2 y no el 1.

**La contradicción, en una línea:** para el mapeo manual y el plan
(`column_mapping_service.ROLE_Y`) la letra `y` significa **NORTE**; en el sniffer
significaba **PROFUNDIDAD**. La misma letra, roles opuestos, y nada que los
comparara. Y `y` **nunca estuvo en el contrato**: el propio mensaje de error del
resolver declara las formas admitidas como «(x_m, z_m), (lat/lon),
(easting/northing), o **(x, z)**». La terna `x, y, z` no figura.

**🔴 LA PRUEBA DE QUE LA AMBIGÜEDAD ES REAL ESTABA EN EL PROPIO CORPUS DE TESTS,
con las dos lecturas a la vez.** `test_r35_flexible_coordinate_parser` usa
`x,y,z` con `y = 5.0` constante — una profundidad de 5 m, la lectura interna. Y
`test_column_mapping._arbitrary_csv` usa `X,Y,Z` con el comentario *«X/Y locales
métricos, Z elevación»* — la lectura del resto del mundo. **Dos ficheros de test,
la misma cabecera, significados opuestos.** El segundo pasaba
mientras el código hacía lo contrario de lo que su comentario declaraba, porque
el único `assert` era `status == "ok"`: **ninguno de los tres ficheros que
cubrían este camino miraba dónde caían las coordenadas.** El tercero
(`test_unit_inference_header`) tenía además `z=0` en todas las filas, es decir
una geometría degenerada —todas las estaciones en norte=0— que tampoco nadie
comprobaba.

**Se cierra por NOMBRE, y la guarda por RANGO no se toca.** La de rango
(`northing_in_depth_slot`, umbral `1e5 m`) es ciega en coordenadas locales: caza
DO-27 (7,1e6) y no Raglan (4,1e4). **Las dos se componen y ninguna sustituye a la
otra**: la de nombre actúa *antes* de que exista una respuesta; la de rango
*después*, y —medido al montar el gate— rechaza mapear a mano un northing de
6,9e6 m al eje vertical. Es decir: el mapeo manual no es una puerta trasera para
reintroducir el defecto.

**Preguntar sin dejar ver la respuesta habría sido un muro.** El sugeridor por
rango propone el par correcto (`x→X` este, `y→Y` norte, confianza **media**,
nunca alta) y ahora se puede leer desde Python: `ColumnPlan.suggestions` es nuevo
—el backend ya lo calculaba y lo publicaba en el contrato, faltaba el accesor—.

**Alcance verificado:** `x_m/y_m/z_m` (convención interna, con sufijo),
`depth`/`profundidad` y el contrato `(x, z)` **siguen sin preguntar**; las tres
familias ambiguas (`x/y/z`, `local_*`, `coord_*`) preguntan, que es el punto 3.

**Una desviación de la letra del punto 1, declarada.** El punto 1 ofrecía pedir
confirmación «cuando `y` aparece junto a `x` y `z` **sin columna de profundidad
declarada**», lo que sugiere que con un `depth_m` al lado podría resolverse solo.
No se hace: el **punto 2 no tiene excepción**, y aunque `depth_m` deje a `y` como
horizontal, sigue sin decir cuál de `y`/`z` es el norte y cuál la cota —
resolverlo exigiría asumir que `z` es la vertical, la misma clase de suposición
que causó H-F11-1, una capa más adentro y por eso más difícil de ver. El coste es
un mapeo manual en un encabezado poco frecuente; el beneficio es que la regla no
tiene bordes y se explica en una frase. Queda pinchado con test propio.

**El gate de física NO se toca, y se verificó en vez de suponerlo:**
`f9_regression_lib.py` no llama al importador — `case_raglan` usa
`raglan_harness.load_raglan_magnetic()`, que arma el frame a mano. Esa misma
elusión es *por qué* el defecto sobrevivió a dos benchmarks externos: los
datasets que lo habrían delatado nunca pasaron por la puerta que lo tenía.

**Gate por MUTACIÓN:** devolver `"y"` al rol profundidad pone **7 de 17** tests de
la fase en rojo —incluido el gate literal y las tres familias— más 3 en otros
ficheros; restaurar vuelve a verde. El test de control (que el detector de
geometría corrupta sabe distinguir) se mantiene verde bajo mutación, que es lo
que impide que el gate pase por vacuidad.

**Efecto colateral medido, y es una deuda ajena:** el presupuesto AST se puso
rojo con **+44 líneas**. Al medirlo, `services.loc` ya estaba en **+4,86 %** del
techo *antes* de esta fase — **1.371 líneas** de las Fases 12-14 que nunca se
re-baselinearon. Se re-baselinea deliberadamente (es el flujo que el propio gate
indica) y conviene saber que **`cc_max` (181) y `func_loc_max` (777) NO se
movieron**: lo que creció son líneas de funcionalidad, no complejidad.

**🟠 LO QUE ESTA FASE MIDIÓ Y NO ARREGLÓ, con nombre — NUEVO-7.** El camino de
usuario está cableado a medias. `PrepEnrichPanel.tsx:324` **sí** reacciona a
`needsMapping` y abre el paso de mapeo manual, así que la pregunta llega. Pero
`suggestions` —la respuesta sugerida por rango, la que convierte la pregunta en
un clic— existe en `types/backend-contracts.generated.ts:210` y **ningún `.tsx`
la lee**: cero consumidores medidos. El usuario de la UI ve «hay que mapear» y
una lista de columnas desnuda, mientras el backend ya sabe cuál es cuál. Desde
Python sí se ve (`ColumnPlan.suggestions`, añadido aquí).

Es la familia **H-10** otra vez —*el backend hace lo honesto y el camino del
usuario se detiene ahí*— y conviene decir por qué el guard de la Fase 9 no lo
caza: ese guard mide **rutas** y **componentes montados**, no **campos de una
respuesta**. Un campo del contrato sin lector es un hueco que hoy nadie vigila.
No se arregla aquí porque **esta fase es de backend** y la regla de oro del
proyecto prohíbe cruzar; queda como trabajo de frontend, hermano de la Fase 20.

---

### FASE 17 (CERRADA) — La corrección de terreno usa la componente vertical · **M** · 🔴 **P0** · *backend* · ACAD-0, ACAD-9

**Por qué va aquí.** Activa por defecto, entra en el dato que se invierte, error
medido de 12× sobre una señal de 0,1–10 mGal. Que un **test tautológico**
congelara la fórmula es parte del defecto: hay que romper el test *antes* de
arreglar el código.

**Trabajo.**
1. Reemplazar `G·ρ·A·|dh|/r²` por la componente vertical de la columna
   (`≈ G·ρ·A·dh²/(2r³)`) en `gravity_corrections_service.py:183`.
2. Reescribir `test_tc_matches_pointmass_formula` para que compare contra un
   **valor de referencia independiente** — el prisma de Nagy, que ya existe en
   `gravimetry.py::_nagy_prism_safe` — y no contra una reimplementación de sí
   mismo con `rtol=1e-9`.
3. Barrer el resto de `tests/` buscando la misma patología: tests que
   reimplementan la fórmula que dicen verificar.
4. Cuantificar el efecto E2E con el Validation Framework y dejarlo escrito: es
   lo que al expediente académico le falta.

**Gate.** El test nuevo **falla con la fórmula vieja dentro**, verificado por
mutación. Y una corrida del benchmark con TC activa vs. desactivada difiere en
la magnitud predicha, no en 12×.

#### ✅ EJECUTADA — 2026-08-25

**La fórmula.** `gravity_corrections_service.py` pasa de `G·ρ·A·|Δh|/r²` a la
componente vertical de la columna, en forma cerrada y estable:

```python
s_m = np.sqrt(r_m ** 2 + dh ** 2)
tc_contrib = _G_NEWTON * rho_kg_m3 * cell_area * dh ** 2 / (r_m * s_m * (r_m + s_m))
```

**Una desviación del punto 1, declarada, y el test la defiende.** El plan pedía
`≈ G·ρ·A·Δh²/(2r³)`. Eso es sólo el **límite de campo lejano**, y tomado al pie
de la letra cambia un desbordamiento por otro: contra el prisma exacto de Nagy,
en terreno escarpado cercano (celda de 50 m, r=50 m) sobrestima **10× con 200 m
de desnivel, 35× con 400 m y 202× con 1000 m**, porque diverge como 1/r³. La
forma cerrada se queda en **0,71–0,99 del prisma** en todo el campo cercano —
siempre por debajo, nunca desbordada. Las dos coinciden lejos: a r=1000 m
difieren 6,7·10⁻⁴. Se implementa la exacta. **La mutación M2 mete la fórmula del
plan y el test la caza**, así que esta desviación no es una opinión.

Y se escribe en forma racionalizada, no como `1/r − 1/√(r²+Δh²)`: esa resta
pierde dígitos por cancelación cuando Δh ≪ r — medido **8·10⁻⁶** de error
relativo a r=22 km con Δh=0,1 m, que es justo el régimen del radio por defecto.

**La no-negatividad deja de ser un recorte y pasa a ser estructural.** Se retira
el `np.maximum(tc, 0.0)`: el numerador es Δh² y el denominador positivo, así que
el recorte ya no puede dispararse nunca. Un guard inerte que aparenta defender
algo es la patología que este repositorio persigue desde la auditoría 06-03.

**El nombre, otra vez.** La Fase 0 renombró `..._prism` → `..._pointmass` porque
el nombre prometía Nagy y la implementación era masa puntual. Arregló el nombre y
dejó viva la fórmula. Ahora la implementación es una **columna**, así que la
función es `compute_terrain_correction_column` y los **dos** nombres históricos
quedan como alias — ningún llamador cambia.

**El test tautológico, sustituido por una referencia independiente.** El viejo
`test_tc_matches_pointmass_formula` reescribía a mano la línea 182 del servicio y
comparaba con `rtol=1e-9`: verificaba que Python sabe multiplicar. El nuevo
compara contra `gravimetry.py::_nagy_prism_safe` — otro módulo, escrito para el
motor directo, que no sabe que la corrección de terreno existe. **12 tests**, de
los cuales tres familias son gates de verdad:
- contra Nagy, **una celda** en campo lejano (r ≥ 20 celdas): concuerda a
  **9,4·10⁻⁴** (r=1000 m) y **2,3·10⁻⁴** (r=2000 m);
- contra Nagy, **un DEM entero** sumado celda a celda, con tolerancia del 25 %
  porque ahí sí entra el campo cercano, más la exigencia de que la columna
  **subestime** al prisma y nunca se pase;
- **leyes de escala** — TC ∝ Δh² y TC ∝ 1/r³ — que discriminan la fórmula vieja
  (∝|Δh|, ∝1/r²) sin necesidad de Nagy.

**Mutación: 4/4.** M1 la fórmula vieja, M2 el campo lejano del plan, M3 la resta
ingenua, M4 `|Δh|` en vez de `Δh²`. Las cuatro fallan; restaurado, 12/12 pasa.
El error de la vieja es `2r/|Δh|` **exacto** (medido 200,01 frente a 200,00
predicho) y **crece con la distancia**: 66× a 1 km con 30 m, **4400× a 22 km con
10 m**, que es el radio por defecto.

**El efecto E2E, medido — y la verdad no se postula.** Sierra sintética de 800 m
de desnivel (DEM 224×224 de 90 m, radio 10 km), 64 estaciones, cuerpo de
0,6 t/m³ entre 300 y 600 m. La **TC verdadera** se calcula sumando el prisma
exacto de Nagy sobre las ~38.800 celdas dentro del radio, estación por estación:

| brazo | media | rango | vs. verdad |
|---|---|---|---|
| **TC exacta (Nagy)** | 4,5234 mGal | 2,608–6,985 | — |
| **TC nueva (Fase 17)** | 4,3991 mGal | 2,488–6,840 | **0,973×** |
| **TC vieja (ACAD-0)** | 91,9703 mGal | 67,167–117,142 | **20,33×** |

Ése es el número que cierra el defecto: la fórmula nueva reproduce el prisma
exacto al **97,3 %**; la vieja lo sobrestimaba **20 veces**. Y el residuo que
cada brazo deja en el dato (`TC_aplicada − TC_verdadera`, porque
`CBA = FAA − BC + TC` y pasarse de TC sesga la anomalía hacia **arriba**):

| brazo | sesgo medio | pico a pico |
|---|---|---|
| TC nueva | −0,1243 mGal | 0,6427 |
| TC desactivada | −4,5234 mGal | 4,3773 |
| **TC vieja** | **+87,4469 mGal** | **45,6520** |

La señal del cuerpo es **1,33 mGal** pico a pico: el artefacto que metía la
fórmula vieja era **66× el sesgo y 34× la variación** de lo que se busca. En la
inversión eso no sesga el modelo, lo **satura**: **4800 de 4800 celdas** por
encima del umbral, Δρ máximo **2,900 t/m³** y **215× la masa verdadera** — la
topografía se convierte en una manta de densidad falsa que cubre el volumen
entero. Con la TC exacta el mismo caso da 372 celdas, Δρ 0,218 t/m³, masa
**1,02×** y **14,7 m** de error de profundidad.

> ⚠️ **No comparar los brazos por `err_prof`.** El brazo corrupto da 150,1 m y el
> ideal 14,7 m, pero el 150,1 es el centroide de una malla **saturada**: es el
> espejismo del centroide que este repositorio ya midió en
> `project_techo_medium_checkerboard`. Las métricas honestas del brazo corrupto
> son 4800/4800 celdas y 215× de masa.

**La corrección se gana el sueldo en el eje HORIZONTAL, que es el que se vende.**
Cuatro brazos, con el DC quitado de cada residuo (para descartar que todo fuese un
offset — no lo era):

| brazo | residuo p-p | err_prof | **err_horiz** | Δρ máx | celdas | masa |
|---|---|---|---|---|---|---|
| IDEAL (TC exacta) | 0,000 mGal | 14,7 m | **0,0 m** | 0,218 | 372 | 1,02× |
| **TC nueva (Fase 17)** | 0,643 mGal | 400,0 m | **53,5 m** | 0,898 | 20 | 0,25× |
| TC desactivada | 4,377 mGal | 400,0 m | **638,2 m** | 0,916 | 68 | 0,87× |
| TC vieja (ACAD-0) | 45,652 mGal | 338,8 m | **678,8 m** | 2,896 | 296 | 11,07× |

**La profundidad NO discrimina: los tres brazos no-ideales dan ~400 m, incluido
«sin TC».** Eso es coherente con lo que este repositorio lleva midiendo desde
`project_synthetic_depth_ambiguity`: la gravedad sola no resuelve profundidad, y
cualquier residuo topográfico basta para tumbarla. **El eje que sí discrimina es
el horizontal** — 53,5 m con la fórmula nueva frente a **~650 m** sin TC o con la
vieja: sin corregir, el objetivo se pierde; corregido, se encuentra. Es
exactamente el eje del producto (targeting, *dónde perforar*, ver
`project_fase25_field_validation`).

**🔴 Lo que la Fase 17 NO arregla, y queda como sucesor.** El residuo baja de 45,7
a **0,64 mGal** p-p… que sigue siendo **el 48 % de la señal del cuerpo**, y con él
la profundidad pasa de 14,7 a 400 m y la masa recuperada de 1,02× a 0,25×.
Colapsar la celda a un punto en el horizontal todavía cuesta caro con 800 m de
relieve y DEM de 90 m. **La salida ya existe en el repositorio**:
`_build_sparse_kernel` usa Nagy exacto en campo cercano y masa puntual lejos
(`gravimetry.py:780`); la TC debería hacer lo mismo con las primeras coronas de
celdas. Fase aparte.

> Alcance honesto: **un** sintético, **una** realización sin ruido, y **λ fijo en
> los cuatro brazos** a propósito, para aislar el cambio en el dato. Producción
> re-elige λ (Morozov/L-curve), así que la degradación real será menor. Sirve para
> ordenar los brazos, no para prometer un número.

**El barrido de tautologías (punto 3): 84 ficheros, 7 supervivientes.** De 19
hallazgos crudos, un pase adversarial descartó 12 (solución analítica publicada,
tests de propiedad, baselines declarados). Sobreviven, **sin corregir — son de
otras áreas y esta fase es de la corrección de terreno**:

| fichero:línea | qué congela |
|---|---|
| `test_multimodal_fusion.py:147` | **El único que congela un defecto plausible REAL**: copia `np.std(arr)/√n` de `multimodal_fusion_service.py:312`, con el `ddof=0` implícito. El error estándar de la media se define con la desviación *muestral* (`ddof=1`); con n=4 el σ del ancla de sondaje queda **13,4 % subestimado** y el test no puede verlo |
| `test_gravity_column_norm_refactor.py:112,160` | Dos tests que **nunca llaman al código bajo prueba**: rearman `Ws` a mano, así que `norma=1` y `cond_post ≤ cond_pre` son ciertos por construcción para cualquier matriz. Además reimplementan un `Wz_inv` que producción ya **retiró** |
| `test_doi_calibration.py:108` | No importa una sola línea de producción: `abs(0.01-0.0)/0.1 == 0.1` es aritmética de Python |
| `test_fase4_depth_weighting.py:182` | Rearma el sistema entero (peso de columna, `alpha_spatial`, calibración `N=256`) y compara a `rel<1e-6`. Sirve como detector de cambios, es ciego al eje que su nombre promete |
| `test_laplacian_weights.py:121` | `2/(a+b)` copiado con `atol=1e-14`; un factor global equivocado es invisible en todo el fichero, porque `L·1=0` se cumple para cualquier peso |
| `test_pgi_engine.py:234` | `√α` copiado de `pgi_engine.py:251` con `rtol=1e-10` |

**El Validation Framework no podía hacer esto, y está declarado en su contrato.**
El punto 4 pedía cuantificar el efecto «con el Validation Framework». No se pudo:
`validation/contract.py:113-117` define `Topography` con un solo modo — *«'flat' =
superficie plana en y=0. Otros modos se añadirán **con su verdad**»* — y
`elevation_m` es un escalar, no un DEM. Un marco que sólo sabe de mundos planos
no puede expresar una corrección de terreno. Por eso la medición se hizo con un
harness propio que sí usa la función de TC de producción y el motor directo e
inverso de producción. **La verdad que le faltaba al framework es justamente la
que esta fase construyó** (la suma de prismas de Nagy sobre el DEM): contribuirla
como un `Topography.kind` nuevo es el camino natural. `python -m
validation.test_determinism` sigue en **8/8** tras el cambio.

**Lo que NO se tocó.** La celda que contiene la estación sigue excluida (r=0), la
sección se sigue colapsando a un punto en el horizontal, y los 7 tests
tautológicos de arriba siguen como están: cada uno vive en un área distinta
(solver, DOI, PGI, laplaciano, fusión) y arreglarlos es otra fase.

---

### FASE 18 (CERRADA) — El experimento que cierra la rotación de 90° · **M** · 🔴 **P0** · *backend, medir* · ACAD-1

**Por qué va aquí.** La inconsistencia está probada por lectura. Lo que **no**
está probado es la consecuencia numérica, y el arreglo depende de saber cuál de
las dos convenciones adoptar. Esta fase **mide**; la 19 corrige. Separarlas evita
el error clásico de este repositorio: parchear la hipótesis equivocada porque
daba el mismo número (fue exactamente lo que casi hunde la Fase 14).

**Trabajo.**
1. Construir un sintético a latitud chilena (`I≈−30°`, `D≈2°`) con un cuerpo
   conocido y correrlo **por el camino de producción completo** — CSV →
   importador → motor — **no** por los harness de benchmark, que arman el frame a
   mano y por eso son ciegos.
2. Comprobar si el eje máx–mín de la anomalía cae Norte-Sur (correcto en el
   hemisferio sur con D≈2°) o Este-Oeste (rotado).
3. Repetir a latitud ártica para demostrar por qué DO-27 y Raglan no lo vieron.
4. Decidir y **escribir** cuál es la convención canónica del backend. Hoy
   `magnetometry.py:31` afirma ser «idéntica a gravimetry» y `gravimetry.py` no
   declara ninguna.

**Gate.** El experimento produce un **número**, no una opinión: el ángulo medido
entre el eje del dipolo recuperado y el esperado, a dos latitudes. Si sale ~90°
en Chile y ~0° en el Ártico, la hipótesis queda cerrada.

#### ✅ EJECUTADA — 2026-08-25

Harness: `scripts/validation/fase18_axis_convention_experiment.py` (4 partes) ·
reporte: `fase18_axis_convention_report.json` · decisión escrita:
**`docs/11_CONVENCION_DE_EJES.md`**. **No se tocó una línea de producción.**

**El número — y el plan pedía uno equivocado.** El gate esperaba «~90° en Chile».
Sale **86,000°**, y la diferencia no es ruido: **el defecto no es una rotación,
es una REFLEXIÓN sobre el azimut 45°.** Producción calcula la respuesta magnética
con una declinación efectiva

```
D_efectiva = 90° − D          (la inclinación queda intacta)
```

y eso es una **identidad, no una aproximación**: ajustando qué par (I', D')
reproduce la salida corrupta, el residuo baja a **~10⁻¹³ nT** en los cuatro sitios
y en dos posiciones distintas del cuerpo. Con `D = 2°` la rotación es `90 − 2·D`
= 86°, no 90°.

| sitio | I | D | D efectiva | predicha | rotación | Pearson r | error/señal |
|---|---|---|---|---|---|---|---|
| **Chile** (defaults) | −30,0° | 2,0° | **88,000°** | 88,00° | **86,000°** | **−0,053** | **1,45** |
| DO-27 (IGRF real) | 83,8° | 25,4° | 64,600° | 64,60° | 39,200° | 0,9945 | 0,103 |
| Raglan (IGRF real) | 83,0° | −32,0° | 122,000° | 122,00° | 154,000° | 0,9407 | 0,336 |
| **Declinación 45°** | −30,0° | 45,0° | **45,000°** | 45,00° | **0,000°** | **1,0000** | **0,000** |

El `r = −0,05` de Chile es el titular: la anomalía que produce el motor **no está
correlacionada con la verdadera**. No es un sesgo, es otro dato. Y el
`error/señal = 1,45 ≈ √2` es la firma aritmética exacta de dos señales
incorreladas.

**La cuarta fila es la que ninguna lectura de código podía dar.** Con `D = 45°`
el defecto es **exactamente invisible** (1,9·10⁻¹³ nT). Si fuera una rotación
rígida de 90°, ahí habría un error del **78 %** de la señal. Se midió: lo hay
para la hipótesis rival, no para producción. Reflexión confirmada, rotación
refutada, con números.

**Por qué DO-27 y Raglan fueron ciegos, en forma cerrada.** Lo que se desplaza es
`f̂` en el marco geográfico, y su módulo vale **√2·cos I·|sin D − cos D|**
(verificado contra el cálculo numérico a 1·10⁻¹⁶): Chile **1,1813**; Raglan
0,2375 (**5,0× menos**); DO-27 0,0725 (**16,3× menos**); D=45° exactamente 0.
`cos I ≈ 0,11` en el Ártico aplasta justo la componente que se refleja. Y la
segunda razón se confirmó por lectura: `ingest_do27.py:100` y
`raglan_harness.py:104` arman el frame a mano *con* la convención del motor, así
que nunca pasan por el importador.

**El camino de producción completo, en tres tramos.** CSV con cabeceras en
español → `import_gravity_csv_v1(data_kind="magnetic")` → empalme literal de
`geophysics_service.py:2107` → motor.

*B1, el contrato de la ingesta* — con una malla de estaciones **deliberadamente
asimétrica** (21 × 13; con malla cuadrada el defecto sería invisible, la misma
lección que el gate de la Fase 19 exige para el ZIP):

```
|x_m − Este| = 0,00e+00 m      |x_m − Norte| = 1200,0 m
span(x_m, z_m) = (1200, 720)   span CSV (E, N) = (1200, 720)
```

El slot `x_m` **es** el easting. Medido, no leído de un comentario.

*B3, el modelo recuperado* (brazo de control = `field_unit_vector` parcheado a la
convención del dato; un instrumento de medida que **no** se escribe en producción
y se restaura en un `finally`):

| geometría | sitio | brazo | err. horizontal | misfit |
|---|---|---|---|---|
| cuadrada 17×17 | **Chile** | **producción** | **150,0 m** | **51,61 %** |
| cuadrada 17×17 | **Chile** | control | **30,0 m** | **1,04 %** |
| cuadrada 17×17 | DO-27 | producción | 30,0 m | 21,67 % |
| cuadrada 17×17 | DO-27 | control | 30,0 m | 21,05 % |
| alargada 21×13 | Chile | producción | 150,0 m | 60,76 % |
| alargada 21×13 | Chile | control | 30,0 m | 22,06 % |
| alargada 21×13 | DO-27 | producción | 30,0 m | 26,41 % |
| alargada 21×13 | DO-27 | control | 30,0 m | 25,72 % |

En Chile el defecto **quintuplica el error horizontal y multiplica el misfit por
50**; en el Ártico los dos brazos son **indistinguibles** (0,6 puntos). El
misfit del 51,6 % es lo que el usuario ve: la inversión **no puede ajustar su
propio dato**, y el producto le entrega igualmente un modelo.

> **Se publican las DOS geometrías a propósito.** La alargada hace decisivo el
> tramo B1 pero le cuesta fit al control (22 % en vez de 1 %); la cuadrada da el
> contraste más limpio pero su B1 no discriminaría. Quedarse sólo con la que
> favorece la conclusión es el vicio que este repositorio persigue.
> ⚠️ **Con el `auto_grid` crudo de este CSV (34×36×34 a 29 m) el experimento NO
> discrimina**: el solver GPCG termina por `(max_outer)` en los DOS brazos, con
> misfit 47–58 % y el pico pegado a 14,5 m. La malla de B3 se **declara**
> (el endpoint acepta `nx/ny/nz` del paquete, `gravity_import_api.py:1731-1733`).
> Que el auto-grid por defecto deje al solver sin converger es un hallazgo
> aparte, y no tiene fase.

**La profundidad no discrimina, otra vez.** −190 m (producción) vs −130 m
(control) sobre una verdad de 220 m: los dos brazos dejan el pico cerca de la
superficie. Es el mismo eje ciego que midió la Fase 17 y que
`project_synthetic_depth_ambiguity` lleva midiendo desde el principio. **El eje
que discrimina es el horizontal.**

**Mutación: 8/8** (Parte D del harness, reproducible).

| mutación | qué rompe | resultado |
|---|---|---|
| **M1** — quitar el defecto | `f̂` en la convención del dato | rotación medida **5,7·10⁻¹⁴°** en los 4 sitios: el harness dice 0 cuando no hay defecto, no se mide a sí mismo |
| **M2** — reflexión vs rotación | compara con la hipótesis rival | producción == verdad a 1,9·10⁻¹³ nT; la rotación rígida de 90° falla por **78 %** de la señal |
| **M3** — ensamblado inconsistente | permuta los sensores y NO los vóxeles | **ningún** (I', D') lo reproduce: residuo **17 %** de la señal. El «88,000° exacto» de la Parte A no es un artefacto del ajustador |
| **M4** — sólo es magnético | permuta consistente sobre el forward GRAVIMÉTRICO | **4,8·10⁻¹⁴** relativo: la gravedad no ve la permutación |

**La decisión (punto 4 del trabajo), escrita en `docs/11_CONVENCION_DE_EJES.md`.**
Canónico: **`x = Este, y = profundidad (+abajo), z = Norte`** — la que la ingesta
**ya implementa y cumple** en sus cinco ramas, la que usan el exportador OMF y el
escritor UBC de disco. La contraria la declaran **28 sitios**, y de ellos **sólo dos
expresiones ejecutables** dependen de ella. Adoptarla **no obliga a permutar
un solo array**; la alternativa obligaría a permutar de vuelta malla, vóxeles,
parquet, cortes, anclajes y los dos exportadores para acabar en el mismo sitio.

**Dos líneas ejecutables, y hay que cambiarlas JUNTAS:**

| ruta:línea | hoy | debe ser |
|---|---|---|
| `magnetometry.py:92-96` | `[cos I·cos D, sin I, cos I·sin D]` | `[cos I·sin D, sin I, cos I·cos D]` |
| `magnetometry.py:2458` | `dec_eff = arctan2(Mz, Mx)` | `dec_eff = arctan2(Mx, Mz)` |

> **Arreglar sólo la primera es peor que no arreglar nada** en modo MVI: kernel
> correcto y declinación publicada todavía reflejada. **La trampa ya está
> puesta:** `tests/test_fase20c_mvi.py:159` exige `|dec_eff − DEC| ≤ 25°` con
> `DEC = 2,0°`; un arreglo a medias devuelve 88° y excede el margen por **86°**.
> No borrarla: es la que caza el arreglo incompleto.
>
> La remanencia (`magnetometry.py:468`) y la amplitud usan la MISMA función:
> se corrigen solas.

**Reversibilidad medida (Parte C): la Fase 19 no le cuesta nada a los
benchmarks.** Voltear `f̂` *y* voltear el ensamblado del harness es un
re-etiquetado consistente: el dato predicho sale **idéntico a 3·10⁻¹⁶ nT** sobre
una señal de ~1 nT, en los cuatro sitios. ⚠️ Lo medido es el **forward**; la
inversión lo hereda por ser el mismo sistema re-etiquetado, pero eso es un
argumento, no una corrida: **la Fase 19 debe correr DO-27 y Raglan de punta a
punta antes y después.**

**Hallazgos nuevos que la fase destapó y NO arregla:**
- **`magnetometry.py:2458`** — segunda fuga independiente: la inversión vectorial
  MVI publica al usuario una declinación de magnetización calculada con la
  convención equivocada (devuelve 65° donde toca 25°).
- **`geophysics_service.py:2433` y `joint_inversion.py:972`** publican al cliente
  `"axis_convention": "x=Norte, z=Este..."`, que es **falso** respecto del
  contenido de los arrays que acompañan. La rama joint declara `x=Norte` en
  `:972` y su propio empalme de `:491` mete el easting en el slot 0.
- **Errata heredada:** `magnetometry.py:31` dice ser «idéntica a gravimetry», y
  `exploration/gravimetry.py` **no declara ninguna convención** en 4365 líneas.
  La afirmación no es verificable contra su fuente — y no podía detectarse por
  resultados, porque la gravimetría es invariante (M4).
- **El defecto real no es la permutación ausente**: es que **nada en el árbol
  compara la convención de la ingesta con la del motor**. La guardia que falta es
  la Fase 19.

> Alcance honesto: sintéticos, sin ruido, λ de producción (1e-4), dos geometrías
> de survey y dos posiciones del cuerpo. La Parte A es **exacta** (identidad
> algebraica verificada a 10⁻¹³) y no depende del sintético; la Parte B sí, y
> sirve para ordenar los brazos, no para prometer un porcentaje.

---

### FASE 19 (CERRADA) — Una sola convención de ejes, con guardia · **M** · 🟠 P1 · *backend* · ACAD-1, ACAD-1c

**Por qué va aquí.** Depende de la 18. El defecto real no es la permutación que
falta: es que **dos módulos documentan convenciones opuestas y nada los
compara**. Se agrupa con el ZIP porque es el mismo error en el otro extremo del
pipeline, y así no se edita dos veces la misma función.

**Lo que la Fase 18 ya decidió, y este punto 1 hay que reescribirlo.** El plan
decía «permutar en el empalme o en la ingesta». **La respuesta medida es
NINGUNA de las dos.** Canónico = **`x = Este, y = profundidad(+abajo), z = Norte`**
(`docs/11_CONVENCION_DE_EJES.md`), que es lo que la ingesta ya cumple; el que se
adapta es el **motor magnético**, y no hay que permutar un solo array.

**Trabajo.**
1. **`exploration/magnetometry.py:92-96`** — `f̂` pasa de
   `(cos I·cos D, sin I, cos I·sin D)` a `(cos I·sin D, sin I, cos I·cos D)`.
   **Y en el mismo commit `magnetometry.py:2458`**, `dec_eff = arctan2(Mz, Mx)`
   → `arctan2(Mx, Mz)`: arreglar sólo la primera deja el modo MVI publicando una
   declinación reflejada. `tests/test_fase20c_mvi.py:159` ya caza ese arreglo a
   medias (excede su margen por 86°) — **no borrarlo.**
   Después, los 26 sitios declarativos, las dos cadenas `axis_convention`
   **falsas** que se publican al cliente (`geophysics_service.py:2433`,
   `joint_inversion.py:972`) y los harness de DO-27/Raglan, **en el mismo commit**
   (su dato predicho es idéntico a 3·10⁻¹⁶ nT — medido en la Parte C).
2. Arreglar `_ubc_msh_text` y `_ubc_mod_text` (`export_service.py:630-642`) para
   que hagan la misma permutación que ya hace la ruta de disco, y escribir el
   origen real en vez de `0 0 0`.
3. Corregir `_gslib_text`, que hoy etiqueta `X_m/Y_m/Z_m` sobre índices internos.

**Gate.** Dos, uno por cada extremo del pipeline:
- **Ejes (ACAD-1).** Correr **DO-27 y Raglan de punta a punta antes y después**:
  sus números deben quedar **idénticos** (la Fase 18 sólo midió el forward). Y un
  test que **compare la ingesta con el motor** — mete un CSV con easting y
  northing distinguibles, comprueba en qué slot cae cada uno y contra qué
  componente de `f̂` se multiplica ese slot. Los tramos B1 y D de
  `scripts/validation/fase18_axis_convention_experiment.py` ya son ese test en
  forma de experimento: convertirlo a `tests/` es el trabajo.
- **ZIP (ACAD-1c).** Un test con **malla NO cúbica** (20×10×20) que compare las
  cabeceras de los dos escritores UBC y exija que coincidan. Hoy salen
  `20 20 10` y `20 10 20`. **Con malla cúbica el defecto es invisible, así que un
  test cúbico no vale.**

#### ✅ EJECUTADA — 2026-08-26

**ACAD-1 y ACAD-1c cerrados**, en tres commits (backend · backend · docs).
Guardias nuevas: `tests/test_fase19_convencion_de_ejes.py` (9) y
`tests/test_fase19_zip_ubc_ejes.py` (8).

**La promesa que NO se sostuvo, y es el titular de la fase.** El plan daba por
puesta una trampa: *«`tests/test_fase20c_mvi.py:159` ya caza el arreglo a medias,
excede su margen por 86°; no la borres»*. **Medido: no lo cazaba.** Ese test
promediaba declinaciones con `np.average`, y las declinaciones por celda que
devuelve MVI barren **±180°**, así que la media aritmética las cancela: daba
**−3,2°** con el código correcto y **−0,8°** con la declinación REFLEJADA — las
dos dentro del margen de 25°. Con la mutación puesta seguía **verde**. Se cambió
a media **circular** (por vector unitario): ahora salen **9,8°** y **80,2°**, que
suman 90 — la firma exacta de la reflexión — y la mutación lo mata. *La fase
descubrió que su propio gate heredado era decorativo.*

**Mutación 4/4** (con hash del fichero verificado antes, durante y después de cada
una, porque el árbol vive en OneDrive y una restauración llegó a revertirse sola):

| mutación | qué revierte | tests en rojo |
|---|---|---|
| M1 | `f̂` a `(cos I·cos D, …)` | **5** |
| M2 | arreglo A MEDIAS: `dec_eff = atan2(Mz, Mx)` | **3** |
| M3 | quitar la permutación UBC del ZIP | **6** |
| M4 | etiquetas de eje de GSLIB y ASEG | **2** |

**Gate de ejes — DO-27 y Raglan de punta a punta, antes y después.**
El plan prometía números **idénticos** apoyándose en la Parte C de la Fase 18.
**No salen idénticos, y ahora se sabe por qué** — la Parte C midió el *forward*
sobre geometría simétrica:

- **DO-27** — *ni una sola clave de `gravity_only` cambió* en las 120 del reporte
  (invarianza exacta de la gravimetría, medida end-to-end, más fuerte que el
  `4,8·10⁻¹⁴` que la Fase 18 midió sólo en el forward). Lo magnético se mueve
  ≤8 m horizontales (0,16 celdas) y ≤16 m en profundidad; **los dos veredictos
  siguen PASS** (tol. 100 m): grav 53,7 m · mag 73,8→**76,9** · joint-grav
  74,4→**82,8** · joint-mag 81,2→**76,0**. Aislado el origen: con la geometría
  REAL de DO-27 el dato predicho por las dos convenciones coincide a
  **1,02·10⁻¹⁶** relativo ⇒ el movimiento vive **entero en el camino del solver**
  (sistema permutado-pero-equivalente, iterando a un iterado ligeramente
  distinto), no en la física.
- **Raglan** — aquí el cambio **sí es geométrico**, y se midió la causa: el survey
  **no es simétrico respecto de la caja de vóxeles**. `east_local` ∈
  [−3,4 , 4004,6] **se sale** de la caja [0, 4000] por los dos extremos;
  `north_local` ∈ [28,0 , 3970,0] **cabe entera**. Voltear los ejes transpone el
  survey contra una caja cuadrada fija y eso no es una simetría de ESTE survey.
  Resultado: la métrica dura **idéntica** (pico interior **212,1 m**, PASS), el
  misfit igual (8,060 → 8,079 %), la correlación igual (0,558 → 0,559), y el
  **artefacto de borde que el propio harness documentaba se disuelve**: pico
  GLOBAL 1202,1 → **212,1 m**. La profundidad empeora (err 50 → 250 m), en el eje
  que este repositorio ya tiene medido como null-space.
  > La colocación de antes era la **arbitraria** —venía de la convención
  > equivocada del motor—; la de ahora es la que coincide con la ingesta y con
  > los ejes (E, N) del propio modelo de referencia.

**Gate del ZIP.** Malla NO cúbica 20×10×20: la cabecera pasa de `20 10 20` a
`20 20 10`, y **3998 de 4000 celdas** caían en distinto sitio según se
descargase el ZIP o se leyese el fichero del disco. En vez de sincronizar dos
escritores se dejó **UNO**: `ubc_mesh_text` / `ubc_model_text` /
`tq_flat_to_ubc_flat`, que usan las dos rutas — verificado **byte-idéntico** al
escritor de disco anterior en 5 formas de malla, así que la ruta de `load-package`
no cambió de comportamiento. El origen ya no es `0 0 0` sino el UTM real, leído
por las dos rutas con la **misma** función (`run_local_origin`).

**Un test de otra fase se puso rojo, y NO se arregló moviendo el umbral.**
`test_magnetic_padding.py::test_padding_makes_edge_source_explainable` exige
misfit > 30 % sin padding y pasó a dar **16,9 %**. La causa, medida: su docstring
dice *«fuente más allá del borde **Este**»* pero desplazaba el cuerpo por el eje
`wz`, que bajo la convención canónica es el **Norte**; el escenario había dejado
de ser el que el test describe. Con I=75°, D=10° la componente horizontal del
campo vale **0,2549** en el Este y **0,0449** en el Norte (5,7×), y es la que
hace inexplicable una fuente desplazada por ese eje. Se movió el cuerpo a `wx`
—el mismo caso físico, bien etiquetado— y el misfit sin padding sube a
**71,1 %** y con padding baja a **2,87 %** (ratio 0,04): el caso queda **más
severo** que antes, no retocado.

**Tres erratas del expediente de la Fase 18**, todas medidas al ejecutarlo:
1. La trampa de MVI no cazaba nada (arriba).
2. De los «26 sitios declarativos», **dos SÍ calculan**:
   `scripts/prepare_test_csv.py:87-89` (`fx`/`fz` del campo regional) y
   `scripts/diagnostics/generar_3csv_multifisica.py:36-38` (el `rvec` del
   generador multi-física). Los dos fabrican datos que entran al motor por los
   slots 0 y 2: había que voltearlos.
3. Faltaba un tercer sitio declarativo: `magnetometry.py:125-128`.

**Alcance que la fase NO tocó, con la línea exacta:**
- **`terraquantum-web/componentes/MagnetizationVectors.tsx:99`** reconstruye
  `f̂ = (cos I·cos D, sin I, cos I·sin D)` sobre ejes de mundo donde `x` lleva el
  **easting** (verificado: `Scene3D.tsx:1094` mapea `cell.x` → x de Three.js), así
  que dibuja las flechas MVI a azimut **90−D**. Es **anterior a esta fase y no
  empeora con ella** —el backend publicaba D antes y publica D ahora—, pero es un
  defecto vivo. Fix: `Math.cos(I)*Math.sin(D), Math.sin(I), Math.cos(I)*Math.cos(D)`.
  Es frontend: la regla de oro lo deja para su propia fase.
- **El reporte DO-27 commiteado estaba obsoleto.** Al re-medir el «antes» salió
  que `do27_validation_report.json` difería de HEAD en **11 claves, todas de la
  rama joint** (joint-mag horiz 61,6 vs 81,2; misfit 2,679 vs 1,269). Sus números
  los produjo un commit anterior. Los dos reportes quedan regenerados.
- **NUEVO — el bundle ZIP se inventa la malla cuando falta `inputs.json`.**
  Medido sobre una corrida con la forma real de `f3_gate/runs/joint96k`
  (48×42×48 @36 m = 96 768 celdas, sin `inputs.json`, como TODAS las corridas
  `api_v0`/v2 en disco): el ZIP entrega una malla **8×8×8 @100 m con 512 celdas**
  —el 0,5 % del modelo, al tamaño de celda equivocado— **sin un solo aviso**
  (`export_service.py`, `inputs.get("nx") or 8`). No es ACAD-1c y no se tocó:
  es un fallback que finge, y merece su propia decisión (leer
  `run_manifest.json → inversion_params`, o fallar en voz alta).

---

### FASE 20 (CERRADA) — El contraste efectivo deja de ser invisible · **M** · 🔴 **P0** · *backend* · `density_min`

**Por qué va aquí, y por qué NO es lo que dice la auditoría delta.** La delta lo llama
«`density_min` desacoplado, PR-AUC 0,035, CRÍTICO». Ese número existe, pero **tu propio proyecto lo
retiró por escrito**. `validation/HALLAZGO_2026-08-06_bound_por_defecto.md` abre con un banner de
corrección que dice, textual:

> «El titular original de este documento era incorrecto por sobre-generalización. […] En el
> **flujo real** —grilla derivada del CSV, que es lo que manda la UI— el efecto catastrófico
> **no ocurre**. […] **La recomendación de invertir el default queda RETIRADA.**»

El 0,035 se midió con **malla forzada de 2250 m sobre un survey de 1500 m**, que no es el camino del
usuario. Al barrer 6 regímenes con 48 inversiones, **ningún brazo domina**: a 250 m el permisivo gana
(PR-AUC 0,890 vs 0,288), a 400 m el estricto gana 10× en profundidad, a 600-900 m da igual porque
ninguno recupera. `density_min` es una **variable de régimen**, no un default roto — que es lo que
`solver_configs.py` decía desde el primer día.

**Citar el 0,035 como defecto abierto es repetir por quinta vez el error que el proyecto ya tiene
documentado: medir una configuración y hablar de otra.**

Lo que **sí** queda accionable lo nombra el mismo documento: el contraste efectivo no se declara en
ninguna parte, nada acopla `density_min` con `base_density`, ningún test cubre el caso desacoplado —
y precisamente **porque el valor correcto depende del régimen, el usuario necesita poder VER cuál le
tocó**.

**Trabajo.**
1. Declarar el **contraste efectivo** (`density_min - base_density`) en el reporte y en la UI, con su
   unidad, junto al **% de celdas que terminaron pegadas al bound** (en la medición iba de 91,3 % a
   0,1 % según el brazo: es el indicador que delata el régimen).
2. Acoplar la validación: si `base_density` se mueve y `density_min` no, **avisar del desacople**.
   No forzar un valor.
3. Test del caso desacoplado, que hoy no existe.
4. **NO cambiar el default.** Está medido que no hay uno correcto.

**Gate.** Una corrida con `base_density` movido y `density_min` sin mover produce un aviso visible
**en la UI**, y el reporte declara el contraste efectivo y el % de celdas en el bound. El test falla
si se borra el aviso.

#### ✅ EJECUTADA — 2026-08-27

Backend puro, como la ficha pedía. Guardia nueva: `tests/test_f20_effective_contrast.py`.

**El titular: la regla que pedía el plan NO es la que dispara en el producto.** El plan
pedía avisar «si `base_density` se mueve y `density_min` no». Esa regla está
—`base_moved_min_at_default`, con su test— pero **no puede dispararse desde la UI**:
`base_density` no viaja. El frontend nunca lo envía (`PrepPanel.tsx:1140` manda
`density_min`/`density_max` y nada más) y `gravity_import_api.py:1859` no lo reenvía, así
que se queda en su default 2,6 en toda corrida de paquete. Lo que SÍ ocurre es lo
**simétrico**: el selector «Litología objetivo» mueve `density_min` y deja el fondo en 2,6,
y **dos de sus tres presets imponen un piso de contraste POSITIVO sin decirlo**:

| preset ofrecido en la UI (`prepPanelState.ts:265-269`) | `density_min` | `base_density` | piso efectivo |
|---|---:|---:|---:|
| Granito (2,6–3,0) | 2,6 | 2,6 | **0,00** — coherente |
| **Magnetita (4,5–5,5)** | 4,5 | 2,6 | **+1,90** ← la roca caja queda FUERA de la caja |
| **Cobre porfírico (4,3–4,8)** | 4,3 | 2,6 | **+1,70** ← ídem |
| estado inicial (`custom`) | 0,0 | 2,6 | −2,60 — permisivo, declarado |

Con piso positivo el contraste 0 —la roca caja— **no es representable**, y toda celda sin
anomalía se recorta al bound inferior. Medido de punta a punta con la magnetita: **76,20 %**
de las celdas activas terminan pegadas al bound y el modelo entero sale con densidad
≥ 4,5 t/m³. Por eso la fase implementa **dos** reglas, ambas por VALOR y no por procedencia
(el camino del paquete pasa `density_min` explícito SIEMPRE, así que `model_fields_set` no
distinguiría nada): `positive_floor` (`density_min > base_density`) y la del plan
(`base_density` fuera de su default de contrato con `density_min` exactamente en el suyo —
leído del modelo pydantic, porque v1 declara 2,6 y v2 declara 0,0).

**Lo que se declara.** `report.effective_contrast`: `base_density`, `density_min/max`,
`contrast_min = density_min − base_density`, `contrast_max`, unidad, régimen con su nota,
`cells_at_bound_pct` con desglose inferior/superior, `n_active_cells` y **de qué fuente
salió el conteo** (R-03 post-clip, que descuenta vóxeles muertos; el solver como respaldo).
También en el reporte HTML, §4.6. El aviso **no toca frontend**: viaja por `warnings[]` y
`technicalSummary.warnings[]`, el canal que `lib/terraquantum/runWarnings.ts` ya normaliza y
`WarningBanner` ya dibuja, montado en `DatosView.tsx:349` y `Exploration3DView.tsx:891`.

**El % de celdas en el bound DISCRIMINA — y de paso destapa algo que nadie había medido.**
Mismo mundo, mismo survey, mismo solver; sólo se mueve el piso:

| régimen | piso de contraste | celdas en el bound |
|---|---:|---:|
| permisivo (2,6 / 0,0 — el default del paquete) | −2,60 | **0,00 %** |
| acoplado (2,6 / 2,6 — no-negatividad) | 0,00 | **68,27 %** |
| piso positivo (2,6 / 4,5 — preset magnetita) | +1,90 | **76,20 %** |

Mismo orden y mismo salto al fondo que el barrido de dos brazos del hallazgo (91,3 % → 0,0 %).
**El dato nuevo es la fila del medio: en la configuración ACOPLADA, la que se considera sana,
el bound ya retiene el 68 % de las celdas activas** — es decir que en ese régimen el bound
no es un guarda-raíl, es el regularizador. No se toca (el hallazgo retira por escrito la
recomendación de mover el default), pero **ahora se ve**.

**El default NO se cambió.** Punto 4 de la ficha, cumplido: la fase declara y avisa; no elige.

**Y una errata de honestidad, de una línea:** la nota de `r05_geometry_audit` decía
«asignadas density=base_density=**2.60** t/m3» **literal**, aunque la corrida usara otra base.
Ahora declara la que usó.

**Gate — mutación 11/11**, con hash del fichero verificado antes y después de cada una
(el árbol vive en OneDrive y una restauración llegó a revertirse sola en la Fase 19):

| mutación | qué rompe |
|---|---|
| M1 | el aviso deja de viajar por `warnings[]` |
| M2 | el reporte no declara `effective_contrast` |
| M3 | la regla `positive_floor` no dispara |
| M4 | la regla `base_moved_min_at_default` no dispara |
| M5 | el contraste se SUMA en vez de restarse |
| M6 | el default de contrato se cablea a mano (v1/v2 dejan de distinguirse) |
| M7 | el % de celdas ignora R-03 y usa el conteo sin corregir |
| M8 | la nota de R-05 vuelve al `2.60` literal |
| M9 | el HTML no dibuja la sección |
| M10 | el aviso pierde los números y queda en adjetivos |
| M11 | el % se inventa un `0,0` cuando no hubo diagnóstico |

**Alcance que la fase NO tocó, con la línea exacta:**
- **NUEVO-8 — `base_density` no viaja desde la UI.** No existe el campo en `PrepPanel` ni la
  clave en la configuración del paquete (`gravity_import_api.py:1841-1890` enumera lo que
  reenvía; `base_density` no está). La fase lo hace **visible** —el aviso nombra los dos
  valores y el piso resultante— pero **cablearlo es frontend + API**, y la regla de oro lo
  deja para su propia fase. Mientras tanto, elegir «Magnetita» en el selector sigue
  produciendo un piso de +1,90 t/m³; la diferencia es que ahora **el usuario se entera**.
- No se movió ningún default de `density_min`, ni se tocó `solver_configs.py`.

---

### FASE 21 (CERRADA) — El veredicto deja de mejorar cuando se mide menos · **S** · 🔴 **P0** · *backend* · ACAD-11

**Por qué va aquí.** Es la mitad barata y segura del problema del techo, y cierra una mentira: hoy el
tope a `MEDIUM` se aplica si el checkerboard **falla**, pero `NOT_RUN` **no tiene efecto**. Es decir:
**el veredicto puede mejorar si corres menos diagnósticos.** En un producto cuyo argumento de venta
es la honestidad, eso es lo único inaceptable.

**Lo que esta fase NO hace: desbloquear `HIGH`.** Ver la Fase 26 y la Fase 30.

**Trabajo.**
1. Que `NOT_RUN` tope igual que `FAIL`, o que la corrida se niegue a emitir veredicto sin ese
   diagnóstico. Una de las dos, decidida y escrita.
2. **Declarar el techo al usuario.** Hoy ve «MEDIUM» sin saber que `HIGH` es inalcanzable por
   construcción. Que el reporte diga que el nivel superior no está disponible, y por qué.
3. Registrar en el reporte **cuál de las entradas del worst-of fijó el veredicto**: el diseño de B3
   ya expone los componentes, falta decir cuál mandó.

**Gate.** Una corrida con el checkerboard desactivado **no puede** dar un veredicto mejor que la
misma corrida con el checkerboard activado y fallando. Verificado por mutación.

#### ✅ EJECUTADA — 2026-08-27

Backend puro. Guardia nueva: `tests/test_f21_verdict_ceiling.py`.

**Punto 1 — la decisión, escrita.** De las dos que el plan admitía se eligió que **`NOT_RUN`
topee igual que `FAIL`**, no que la corrida se niegue a emitir veredicto. Motivo: el
checkerboard es un diagnóstico accesorio y **non-fatal** —`_checkerboard_qa` se traga la
excepción y deja `_cb_qa = None`—, así que convertir su caída en un bloqueo dejaría sin
veredicto a una corrida cuya física es válida, castigando al usuario por un fallo del motor.
Topear conserva la semántica del worst-of (*ausencia de evidencia ≠ evidencia de resolución*)
y vuelve el veredicto **monótono**: ningún diagnóstico que se deje de correr puede subir el
nivel. `PASS` y `WARNING` sí son evidencia medida y no topean; **cualquier otro estado,
incluido uno inesperado, se trata como no medido y topea** — el default seguro es el techo,
no la libertad.

`FAIL` y `NOT_RUN` topean igual pero **no se confunden**: uno etiqueta
`checkerboard_resolution` y el otro `checkerboard_not_run`, con motivos distintos y con
`structural` distinto (el FAIL no lo levanta más dato; el NOT_RUN sí lo levanta correr el QA).

**Punto 2 — el techo, declarado.** `overall_verdict.ceiling`: nivel máximo alcanzable, quién
lo topa, si es **estructural**, por qué (con el número medido: `pearson_r = 0,1162` idéntico
a cuatro decimales en 9 corridas frente a un umbral de PASS de 0,60, porque el examen alterna
signo **celda a celda** y eso está por debajo del límite físico de resolución de un campo
potencial), qué haría falta para levantarlo y **dónde está la evidencia**. Y no sólo en el
JSON: va en el **titular** —«MEDIUM» a secas se lee como *confianza media* cuando el sistema
quiere decir *no tengo forma de decírtelo*—, en el reporte HTML §3.5, en el manifiesto del ZIP
industrial y en la trilogía B3 que consume el copiloto.

**Punto 3 — quién mandó.** `overall_verdict.signals` lista **todas** las entradas del worst-of
con su nivel mapeado y `is_limiting`, ordenadas por severidad; `decided_by` nombra las que
fijaron el mínimo (pueden empatar, y se nombran todas). `components` ya publicaba los valores
crudos; faltaba decir cuál mandó.

**Dos tests existentes se pusieron rojos, y NO se arreglaron moviendo un umbral.**
`test_r06_false_alarm_chi2_only_does_not_cap` y `test_clean_all_high_stays_high` afirmaban
`HIGH` **con el checkerboard AUSENTE del payload** — o sea, aprobaban apoyándose justo en el
agujero que esta fase cierra. Se les declaró `checkerboard_qa: {"status": "PASS"}`: siguen
midiendo lo suyo (que el falso positivo de r06 no capa; que un caso bueno no se degrada) y
ahora la dependencia es visible en vez de tácita.

**Y un defecto encontrado al cablear el techo al entregable:** el manifiesto del ZIP
industrial leía `report["checkerboard_pearson_r"]` (`export_service.py:781`), una clave que
**nadie escribe nunca** — grep sobre todo el backend: cero escrituras. El cliente recibía un
bloque `checkerboard_qa` con `pearson_r: null` y **sin `status`**: el nombre del diagnóstico y
ninguno de sus dos números. Ahora lee `checkerboard_qa` y lleva además el techo del veredicto.

**Gate — mutación 17/17**, con hash de los cuatro ficheros verificado antes y después de cada
una. Las cuatro primeras atacan el corazón de la fase:

| mutación | qué rompe |
|---|---|
| M1 | **`NOT_RUN` vuelve a no topear — el defecto original** |
| M2 | el checkerboard deja de topear del todo |
| M3 | un status inesperado deja el techo libre |
| M4 | `FAIL` y `NOT_RUN` dejan de distinguirse |
| M5-M7 | el techo se declara siempre HIGH · pierde su número medido · miente sobre `structural` |
| M8 | el titular deja de nombrar el techo |
| M9-M11 | el ledger no marca quién mandó · sólo lista limitantes · pierde el orden |
| M12 | `pearson_r` deja de viajar con los componentes |
| M13-M14 | el HTML no dibuja el techo · ni el ledger |
| M15-M16 | el ZIP vuelve a la clave muerta · omite el status |
| M17 | el copiloto deja de decir el techo |

**Lo que esta fase NO hizo, a propósito:** desbloquear `HIGH`. El orden sigue siendo **Fase 26
primero, Fase 30 después**. Hoy el techo protege — 1 de cada 3 realizaciones de ruido desvía
el blanco ~170 m con diagnósticos idénticos, y liberar el techo antes de que la señal
discrimine produciría `HIGH` en corridas de 285 m de error.

---

### FASE 22 (CERRADA) — Las unidades de la exportación dejan de mentir · **S** · 🟠 P1 · *backend* · ACAD-12, ACAD-13

**Por qué va aquí.** Dos errores pequeños en el mismo archivo de salida, ambos
nacidos de un cambio cosmético: un renombrado «compliance-safe» que convirtió
toneladas en kilos, y un literal que se quedó cuando `base_density` se volvió
configurable. Se agrupan porque tocan la misma función.

**Trabajo.**
1. `bulk_rock_mass_kg`: o multiplicar por 1.000, o renombrar a
   `bulk_rock_mass_t`. Decidir **mirando si alguien la consume**.
2. Sustituir `VTK_BASE_DENSITY = 2.6` por la `base_density` de la corrida.

**Gate.** Un test que invierte con `base_density ≠ 2.6` y exige que la columna
exportada coincida con la que consume el frontend (`density_contrast_t_m3`).
Hoy divergen.

#### ✅ EJECUTADA — 2026-08-27

Backend puro. Guardia nueva: `tests/test_f22_export_units.py` (29 tests).

**Las dos fichas describían un defecto más pequeño que el real.** Ninguna de las dos era
falsa; las dos se quedaron cortas, y en los dos casos por la misma razón: se leyó la
función donde vive el número y no se comprobó **con qué la llama producción**.

**ACAD-13 estaba en TRES escritores, no en uno.** La ficha nombra
`VTK_BASE_DENSITY = 2.6`. Los otros dos:

*(Líneas contadas sobre `HEAD` = `2418f21`; en el árbol de trabajo están desplazadas por
las Fases 20 y 21, que aún no están commiteadas.)*

| dónde | qué escribía | llega al cliente como |
|---|---|---|
| `export_service.py:31,212` — `build_vtk_core_arrays` | `Density_Contrast_gcm3` del `.vtr` | `model.vtr` del ZIP |
| `gravimetry.py:4213` — `TargetingEngine.extract_and_export` | `density_contrast` del parquet | — (fichero legado) |
| **`export_service.py:947,973` — `_aseg_gdf2_dat_text`** | **`Density_Contrast` del ASEG-GDF2** | **`model.dat` del ZIP** |

El tercero es el grave: ASEG-GDF2 es **entrega regulatoria** en Australia y Nueva Zelanda,
y su fichero de definición `model.dfn` **declaraba por escrito** «Density minus 2.6 g/cm3
base». Declarar una base que no es la usada no hace el número feo: hace el fichero
incorrecto por contrato. Y hay un cuarto sitio que repetía la mentira en prosa: la nota
del bloque `vtk_export` del reporte (`geophysics_service.py:5128`) decía «Densidad base:
2.6 g/cm³» como texto fijo, así que aun con el `.vtr` corregido el reporte seguiría
diciéndole al usuario contra qué **no** se calculó.

**El defecto es alcanzable en producción, y se midió por dónde.** `base_density` no
aparece **ni una vez** en todo `api/`: por el camino del paquete y el del importador se
queda siempre en 2,6, y ahí el literal acierta por accidente. Pero
`POST /geophysics-invert` y `/v2/geophysics-invert` reciben el esquema crudo, así que la
API directa y el scripting **sí** lo mueven — y con `base_density = 4,5` (magnetita, el
ejemplo del propio contrato) el `.vtr` y el parquet que pinta el frontend divergen en
**1,9 t/m³ constantes**: la pantalla y el fichero entregado describen dos cuerpos
distintos.

**ACAD-12: el factor no era 1.000, sino 1.000 · dx³/1.000.** La llamada de producción no
pasaba `block_size`, de modo que la firma caía en su default de **10 m** y el volumen de
celda quedaba clavado en 1.000 m³ *cualquiera fuese la malla* — y encima había un tope
silencioso, `MAX_BLOCK_VOLUME_M3 = 1_000_000`, que recortaba toda celda de más de 100 m
sin decirlo. Medido sobre `data/projects`: **1.034 de 2.089 corridas** usan un dx distinto
de 10 (hasta 8.315 m), y sobre el parquet real en disco la columna vale exactamente
`1.000 × densidad` con dx = 125 m, es decir **1,95 millones de veces** menos masa de la
que la celda contiene. Tampoco se pasaban `ix/iy/iz`, que se re-derivaban como
`floor(coord/10)`. Renombrar el sufijo y dejar eso vivo habría cerrado un factor 1.000 y
conservado uno de hasta 10⁹.

**Punto 1 — la decisión, medida y no opinada.** De las dos que el plan admitía se eligió
**renombrar**, por tres razones que son datos y no criterio:
1. **Cero consumidores.** Grep sobre el monorepo entero —backend, frontend, scripts de
   validación, notebooks, docs—: nadie lee `bulk_rock_mass_kg`. Y el fichero que la lleva
   es un residuo: `df_full` **sobrescribe** `block_model_001.parquet` al final de la misma
   corrida (medido en disco: 28 columnas del esquema canónico, ninguna del TargetingEngine),
   así que la columna sólo sobrevive en el `_anomaly.parquet` global.
2. **El repositorio ya resolvió este mismo defecto así.** El commit `d424c7c` renombró
   `modeled_rock_mass_kg` → `modeled_rock_mass_tonnes` en la ruta canónica. El
   TargetingEngine es el sitio que ese renombrado no alcanzó.
3. **Multiplicar por 1.000 habría producido un número igual de falso**, porque el volumen
   estaba mal por su cuenta.

**Desviación declarada del plan:** el nombre es `bulk_rock_mass_tonnes`, no
`bulk_rock_mass_t`. Se sigue la palabra que el propio repositorio eligió en `d424c7c`,
para que las **dos** columnas de masa del producto se llamen igual — y un test exige que
den el **mismo número**, que es lo que convierte esto en una corrección y no en un cambio
de etiqueta.

**Punto 2 — el literal, sustituido en los cuatro sitios.** `VTK_BASE_DENSITY` **se borra**
en vez de corregirse: el defecto no era su valor sino su existencia. `base_density` pasa a
ser argumento **obligatorio y sin default** de `build_vtk_core_arrays`, `export_core_to_vtr`
y los dos escritores ASEG — olvidarlo es un `TypeError`, no un sesgo silencioso. En el
`.vtr` y en el TargetingEngine el valor es `inversor_core.base_density`, **el mismo objeto**
con el que se construye `density_contrast_t_m3`, para que no puedan divergir. En el ZIP
—que lee del disco, no de la corrida— se añade `base_density_of_run(inputs, report)`, que
devuelve **el valor y su fuente**: `report.effective_contrast` (lo publicó la Fase 20),
`inputs.json`, o `contract_default_assumed`. El manifiesto declara las tres cosas, porque
un contraste sin su referencia es media resta, y «asumido» y «medido» no son lo mismo.

**Tres defectos laterales encontrados al medir, y cerrados:**

1. **`inputs.json` no traía `base_density` — en 0 de 2.089 corridas.** Y no porque nadie la
   moviera: `build_run_inputs_snapshot` es una **lista blanca escrita a mano** de 16 claves
   y ésa no estaba. El audit trail de la corrida no registraba la densidad respecto de la
   cual toda la física está definida. Ahora sí. (No entra en `_AUDIT_KEYS`, así que el
   `config_hash` de las corridas existentes **no** se mueve; hay un test que lo fija.)
2. **`_densities_from_parquet` devolvía `[2.6] * n` cuando faltaba el parquet** — un modelo
   uniforme de roca **inventado** que salía por `model.den`, `model.gslib` y `model.dat`
   con la misma cara que un resultado de inversión. Ahora devuelve NaN, que el escritor UBC
   ya traduce a NODATA: un fichero que dice «no hay dato» en lugar de uno que dice «hay
   2,6 t/m³ en todas partes».
3. **La misma función aceptaba `density_contrast` por el hueco de la densidad ABSOLUTA.**
   De haberse alcanzado esa rama, el `.den`/`.gslib`/`Density_gcm3` habrían llevado un
   contraste rotulado como densidad — el defecto de esta fase con el signo cambiado.
   Medido: `density` está en **2.684 de 2.684** parquets de corrida y `density_absolute` en
   **0**, así que las dos ramas extra eran código muerto con un filo. Retiradas.

**Gate — mutación 24/24**, con hash de los tres ficheros verificado antes y después de cada
una. Las cuatro primeras atacan el corazón de la fase:

| mutación | qué rompe |
|---|---|
| M1 | **el `.vtr` vuelve a restar el literal 2.6 — el defecto original** |
| M11 | **vuelve el nombre en kg sobre un valor en toneladas** |
| M12 | vuelve el tope silencioso de volumen |
| M13 | el TargetingEngine vuelve a restar el literal |
| M2/M2b | `base_density` del `.vtr` recupera un default: olvidarlo deja de ser un error |
| M3-M4 | producción pasa el literal al `.vtr` · la nota del reporte vuelve a decir 2.6 |
| M5-M7d | el ASEG-GDF2 vuelve al literal en el dato, en la definición, en el bundle y por default |
| M8-M10 | la base deja de leerse del reporte · una base no numérica se cuela · el manifiesto deja de declararla |
| M14-M16 | producción deja de pasar `block_size` · `ix/iy/iz` · `base_density` |
| M17-M18 | vuelve la roca inventada a 2.6 · un contraste vuelve a servirse como densidad absoluta |
| M19-M20 | el snapshot pierde la base · `base_density` entra en `_AUDIT_KEYS` y mueve el hash existente |

**El gate del plan, al pie de la letra y un poco más:** la corrida real con
`base_density = 4,5` no compara arrays en memoria — **parsea el `.vtr` que quedó escrito en
disco**, que es el fichero que el cliente abre en ParaView, y exige que coincida celda a
celda con `density_contrast_t_m3`. Además comprueba que el caso **no es trivial**: que con
el literal viejo la diferencia sería 1,9 t/m³ exactos. Sin eso, un test que pasara con
`base_density = 2,6` se leería como gate y no mediría nada.

**La campaña de mutación tuvo un falso negativo, y se corrigió el instrumento.** Una
pasada informó `M16 ESCAPO`; al repetirla a mano se caza **3 de 3**. La causa: OneDrive
revierte ficheros a mitad de la corrida, así que pytest llegó a ejecutarse contra el
fichero **sin mutar** — y una campaña que corre contra código sano informa «escapó», que
es el peor error posible en un gate por mutación. El arnés ahora verifica que la mutación
sigue puesta **antes y después** de pytest y reintenta si no; con esa guardia el
fenómeno se reprodujo y quedó registrado (`M7d INVALIDA`). Es la misma trampa que anotó la
Fase 19, un escalón más arriba.

**Lo que esta fase NO hizo, y queda declarado:**
- **NUEVO-9 — el `config_hash` del ZIP es ciego a la roca caja.** `_AUDIT_KEYS`
  (`export_service.py:612`) no incluye `base_density`, `density_min` ni `density_max`: dos
  corridas que sólo difieren en la densidad de fondo salen con el **mismo hash de
  auditoría**. Se deja abierto a propósito — tocarlo cambia el hash de todo lo existente y
  hay dos listas paralelas que sincronizar (`reporting/report_generator.py`), lo que excede
  una fase «S». Hay un test que fija el estado actual para que el cambio, cuando llegue,
  sea deliberado.
- **`DatosView.tsx:98` lee `persistedReport.density_contrast`, una clave que el backend
  nunca escribe** ⇒ muestra «No disponible» siempre. Familia H-10/NUEVO-7. Es frontend, y
  esta fase es backend.
- El parquet del TargetingEngine sigue escribiéndose en una ruta **relativa al CWD** y
  sobrescribiéndose dentro de la misma corrida. Se corrigió lo que contiene, no dónde vive.

---

### FASE 23 (CERRADA) — La inversión conjunta recupera topografía y avisos · **M** · 🟠 P1 · *backend* · NUEVO-1

**Por qué va aquí.** La Fase 1 cerró H-27 en dos de las tres rutas. La que quedó
fuera es la conjunta — el caso de los dos CSV, el que más diferencia al producto
de una hoja de cálculo. Un modelo conjunto puede caer a topografía plana y salir
con sello de bueno.

**Trabajo.**
1. Cablear `topography_run_warnings` en `services/joint_inversion.py`, igual que
   en las rutas gravimétrica y magnética.
2. Comprobar los **tres eslabones** (emisión → respuesta → componente montado),
   como exige la pregunta 2 de la plantilla de gate.

**Gate.** Correr la conjunta sin DEM y exigir que el aviso aparezca en el JSON
**y** en la UI. El test debe fallar si se borra el cableado.

#### ✅ EJECUTADA — 2026-08-31

Backend puro. Guardia nueva: `tests/test_f23_joint_topography.py` (16 tests).

**La ficha describía un defecto más pequeño que el real — tercera vez seguida.** NUEVO-1
dice que a la conjunta «le falta el canal de avisos». Lo que había es que
`joint_inversion.py` pasaba `topography_elevations=None` **fijo** a los dos motores
(líneas 585 y 605 de `HEAD`), con una razón escrita en su propio docstring: con todas
las celdas activas los bloques cross-gradient, de nC columnas, conforman con el modelo
sin remapeo. Es decir, la topografía se había cambiado por comodidad algebraica, y eso
no estaba declarado en ninguna parte que el usuario pueda leer.

**Medido antes de tocar nada** (ladera de 240 m de desnivel, malla 8×8×8 de 60 m, las
dos físicas con señal real):

| | sin `sensor_elevations_masl` | con `sensor_elevations_masl` |
|---|---|---|
| huella del modelo | `f1c661a942a511aa` | **`f1c661a942a511aa`** |
| celdas declaradas activas | 512 | 512 (de 360 reales) |
| contraste recuperado **en el aire** | 15,93 % | 15,93 % |
| `topography_used` / `warnings` | ausentes | ausentes |

La cota que el usuario sube en su CSV **no tocaba la física**: el modelo sale idéntico
bit a bit. Y llega de verdad — `sensor_elevations_masl` se rellena en
`gravity_import_api.py:1861` (paquete) y `:2844` (importador v1), los dos caminos que
también rellenan `magnetic_nt`, que es lo que despacha a la conjunta. Sobre
`data/projects`: **617 corridas conjuntas**, ninguna declara estado de topografía; de
las 1.761 que sí lo declaran, **651 (37 %) usaron superficie real**, así que el caso no
es teórico. Las propias fixtures de la tormenta F8 llevan `elev_m` **siempre**
(`f8_storm_lib.py:54`) y seis de sus corridas son conjuntas.

**El trabajo que pedía el plan, tal cual, habría dado un gate decorativo — y así queda
declarado.** «Cablear `topography_run_warnings`» no basta: esa función devuelve lista
vacía salvo en `flat_fallback`, y una ruta que **nunca intenta interpolar** no puede
llegar a ese estado. El gate del plan («correr la conjunta sin DEM y exigir que el aviso
aparezca») tampoco puede dispararse: la Fase 1 decidió —y con razón— que un survey sin
cota es una **entrada declarada por el usuario**, no una degradación, y no avisa. Por eso
esta fase hace **las dos cosas**: usar la topografía y declararla. Es la misma trampa que
cazó la Fase 19 en su propio gate heredado.

**Cómo se resolvió la excusa algebraica.** El docstring tenía razón en el hecho y no en
la conclusión: los bloques de acoplamiento tienen que conformar con el espacio del
solver, pero eso se arregla **recortando** el bloque, no tirando el terreno — y la
propia Fase 9C-1 ya lo hacía para la poda observable (`B[:, _obs_mask_g]`). Ahora ese
recorte se **compone** con la máscara de aire: gravedad resuelve en (activas →
observables), magnetometría en (activas), y cuatro proyectores pequeños llevan bloques y
referencias de la malla al espacio de cada motor. El kernel cacheado —que existía
porque la geometría no cambia entre iteraciones— sigue siendo válido: la máscara de aire
tampoco cambia.

**Medido después**, mismo experimento:

| | sin cota | con cota | con cota, interpolación rota |
|---|---|---|---|
| `topography_used` | `flat` | `from_sensor_elevations_masl[linear+nearest_fallback]` | `flat_fallback` |
| `mesh.n_active` / `n_air` | 512 / 0 | **360 / 152** | 512 / 0 |
| contraste en el aire | 15,93 % | **0,00 %** | 15,93 % |
| error del centroide de masa | 25,8 m | **5,6 m** | 25,8 m |
| avisos al usuario | 0 | 0 | **1** (texto H-27) |
| huella del modelo | `f1c661a942a511aa` | `d92901b4a2facc09` | `f1c661a942a511aa` |

Las 152 celdas de aire que el motor enmascara son **exactamente** las 152 que la
geometría de prueba tiene sobre el terreno. El misfit sigue en 0,006 %: el dato se
sigue explicando, sin masa en el cielo. Y la primera columna es la prueba de que el
camino histórico **no se movió**: misma huella que antes de la fase.

**Una sola preparación de topografía para las tres rutas.** La regla estaba copiada en
la ruta gravimétrica y en la magnética, y ausente en la conjunta — que es exactamente
cómo se produce este defecto. Ahora vive en
`geo_utils.prepare_topography_from_elevations` y la usan las tres: *una copia que no
existe no se puede quedar atrás*. Las dos rutas que ya funcionaban quedaron
**byte-idénticas**, verificado por huella del modelo antes y después de la extracción
(`5de4575f45220e73` gravedad, `8b094f78e2acfe43` magnetometría).

**Cuatro defectos laterales encontrados al medir, y cerrados:**

1. **`solve_inversion_lsqr` aceptaba un kernel cacheado sin mirar su forma.** El motor
   magnético sí compara `override_kernel.shape` con `(n_obs, n_active)`; el gravimétrico
   lo tomaba tal cual. Con topografía activa, un kernel de malla completa habría
   emparejado la columna *k* con la celda *k* equivocada: un modelo **desplazado**, no un
   error. Ahora los dos gritan.
2. **`mesh.n_active` del reporte conjunto contaba TODAS las celdas del core**, aire
   incluido. Ahora cuenta terreno y publica `n_air` y `mesh.topography`.
3. **La mixtura petrofísica del PGI se bootstrapeaba sobre la malla entera.** Con
   topografía el aire entraría como un cúmulo enorme en `(base_density, 0)` y se llevaría
   una de las K clases. Se ajusta sólo sobre terreno, y el reporte declara sobre
   cuántas celdas se ajustó (`coupling.pgi_bootstrap_cells`).
4. **El aviso de contraste efectivo de la Fase 20 tampoco llegaba a la conjunta**, que
   invierte densidad con los mismos `base_density`/`density_min`. Viaja por el mismo
   canal.

**Una puerta de CI se puso en rojo al medirla, y no se cerró subiendo el techo.**
`scripts/ci/ast_budgets.py` marcó `run_joint_inversion`: **861 líneas contra un techo de
777** (816 con la tolerancia del +5 %). El propio arnés ofrece `--update` «si el
crecimiento es deliberado»; se hizo lo otro, porque esa función ya es de las peores del
repositorio (CC 87) y subirle el techo es la manera de que nunca se arregle. Se
extrajeron dos piezas con nombre —`_preparar_topografia_conjunta` (43 líneas) y
`_proyectores_al_espacio_del_solver` (30)— y el presupuesto vuelve al verde **sin tocar
el techo**. Después del refactor el gate se volvió a medir **por mutación en el sitio
nuevo del código**: un refactor no queda demostrado porque los tests sigan pasando.

⚠️ **Y queda dicho lo incómodo:** la función acaba en **812 líneas**, a **4** del techo
con tolerancia. La siguiente fase que la toque no podrá añadir nada sin partirla de
verdad — que es la deuda que la Fase 8 sí pagó en `solve_inversion_lsqr` (2.030 → 152).

**Los tres eslabones, comprobados (pregunta 2 de la plantilla).** *Emisión*: los tres
campos en el `report`. *Respuesta*: el `report.json` que persiste
`write_run_report_snapshot` — hay un test que lo lee **del disco**, no de memoria.
*Componente montado*: `lib/terraquantum/runWarnings.ts::extractRunWarnings` lee
`report.warnings[]` y lo pintan `Exploration3DView` (`data-testid="run-warnings"`) y
`DatosView` (`datos-run-warnings`); es genérico **por corrida, no por motor**, y la
conjunta cierra con el mismo `update_run_status("done")` que las otras dos, así que la
vista pide su reporte igual. Por eso la fase es backend puro y **no toca un solo
`.tsx`**; lo que sí hay es un test que afirma la **forma exacta** que ese lector
consume (lista de strings no vacíos), porque una forma distinta dejaría el banner mudo
sin error visible.

**Gate — mutación 24/25**, con hash del fichero verificado antes y después de
cada pytest (la guardia que la Fase 22 tuvo que inventar porque OneDrive revierte
ficheros a media corrida, y una campaña que corre contra código sano informa
«escapó»). **La primera vuelta dio 21/24, y los tres escapes enseñaron
más que las 21 cazadas.** Dos (M4, M5) eran **ceguera del gate**: el bloque
cross-gradient no se construye en k=1 —el warm-up va sin acoplamiento, por
diseño— y el sintético convergía ahí, así que el recorte que la mutación
rompía **nunca se ejecutaba**. Se añadió un test que fuerza k=2 y las dos se
cazan. El tercero (M8) es de otra clase y por eso **sigue escapando, declarado**:
quitar el filtro de aire del bloque 3D no cambia nada, porque el motor devuelve NaN
en el aire y `nan_to_num` lo deja en contraste **exactamente 0**, que ningún corte
deja pasar. Una línea que ninguna mutación distingue no es una defensa: se conserva
como cinturón y tirantes, pero lo que la fase publica en su lugar es el invariante
**medido** — `mesh.n_air_cells_filtered`, 0 en toda corrida sana — y ahí sí hay
mutación que lo caza (M8b). Las tres primeras atacan el corazón de la fase:

| mutación | qué rompe |
|---|---|
| M1 · M2 | **los motores vuelven a recibir `topography_elevations=None` — el defecto original** |
| M3 | el kernel cacheado vuelve a la malla completa (el guard nuevo lo caza) |
| M4-M7 | bloques y referencias de acoplamiento dejan de recortarse al espacio del solver |
| M8b · M24 | el invariante del aire deja de medirse · con padding, la máscara no se reduce al core |
| M9-M11 | `n_active` vuelve a contar aire · `n_air` miente · `mesh.topography` dice siempre plano |
| M12-M17 | el canal de avisos: sin `warnings`, sin `topography_degraded`, sin el texto H-27, sin el de la Fase 20, y el reporte del disco sin ellos |
| M18 | la mixtura PGI vuelve a ajustarse incluyendo aire |
| M19-M20 | la preparación compartida ignora las elevaciones · el fallo de interpolación se disfraza de survey sin cota |
| M21 | el motor gravimétrico vuelve a aceptar un kernel que no conforma |
| M22-M23 | las **dos rutas que ya funcionaban** dejan de declarar su degradación |

**Regresión:** 41/41 en `test_fase1_confianza_camino_dorado`, `test_fase0_joint_continuation`,
`test_joint_observable_pruning`, `test_joint_structural_similarity`,
`test_fase3_joint_coupling`, `test_magnetic_production_padding` y
`test_bouguer_topo_consistency`.

**Lo que esta fase NO hizo, y queda declarado:**
- **La regla de la máscara activa sigue escrita dos veces.**
  `potential_field_core.active_cells_from_topography` existe y la usan los caminos de UQ,
  DOI y live-update (8 llamadas), pero los **dos solvers principales** conservan su copia
  en línea — la de gravimetría porque lleva la variante cut-cell. La conjunta usa la
  compartida. Unificar los dos motores es un cambio de motor, no de orquestador.
- **La normalización `lambda_cross_eff` usa la norma del bloque COMPLETO** aunque el que
  se inyecta es el recortado. Es la convención que ya tenía la ruta con poda; cambiarla
  movería resultados existentes sin evidencia de que mejore, así que se conserva y se
  declara.
- **`extract_geological_bodies` sigue corriendo sobre el core completo**, aire incluido.
  Esas celdas llevan contraste 0, así que no pueden formar cuerpo; no se tocó.
- Nada del frontend: `NUEVO-2`, `NUEVO-3`, `H-36` y `NUEVO-7` siguen donde estaban (son
  las Fases 24 y 25).

---

### FASE 24 (CERRADA) — La preparación deja de evaporarse · **M** · 🟠 P1 · *frontend* · NUEVO-2, NUEVO-3

**Por qué va aquí.** Es la peor experiencia del producto y la más fácil de
reproducir delante de un cliente: el usuario corrige un CSV, cambia de pestaña
para mirar el 3D, vuelve, y ha perdido el mapeo de columnas, los puntos Helmert,
los sondajes y 25 parámetros. Y el paquete se rearma sobre el CSV crudo — es
decir, **corrige, y su corrección no llega**.

**Trabajo.**
1. Subir el estado de `PreparacionView` al store: el refactor que la Fase 13 se
   prohibió hacer «de paso» y que ahora es el trabajo de su propia fase.
2. Hacer que el CSV corregido sea el que viaja al paquete, no el crudo.
3. Clasificar los campos nuevos en `store/deshacible.ts`, que ya obliga a
   hacerlo por tipos.

**Gate.** Un e2e que mapea columnas, corrige el CSV, navega a otra pestaña,
vuelve, y comprueba que los 25 parámetros y el CSV corregido siguen ahí — **y que
el paquete generado contiene el corregido**, no el crudo.

#### ✅ EJECUTADA — 2026-09-02

Frontend puro; el backend no se tocó. Guardia nueva:
`e2e/fase24_preparacion_persistente.spec.ts` (8 recorridos). Piezas nuevas:
`store/preparacion.ts` (47 l), `componentes/prep/prepEnrichState.ts` (158 l, un
traslado sin lógica nueva salvo una caducidad).

**El defecto era DOS defectos apilados, y el de abajo no estaba en ninguna ficha.**
NUEVO-3 dice «el CSV corregido se descarta al cambiar de pestaña y el paquete se
rearma sobre el crudo». Al medirlo apareció una capa por debajo: el validador local
`parseCsvForValidation` compara la cabecera con una lista **por igualdad**
(`header.indexOf`), y el asistente de correcciones titula su columna con
`outputGravityColName(...)`, que sólo puede valer `g_corrected`,
`free_air_anomaly`, `bouguer_anomaly` o `complete_bouguer_anomaly`. **Ninguno de los
cuatro estaba en la lista** — `"bouguer"` no casa con `"bouguer_anomaly"`. Ejecutando
la propia función:

| columna de salida del asistente | `gIdx` | `can_invert` |
|---|---|---|
| `g_corrected` | −1 | **false** |
| `free_air_anomaly` | −1 | **false** |
| `bouguer_anomaly` | −1 | **false** |
| `complete_bouguer_anomaly` | −1 | **false** |
| *(el CSV crudo, de control)* | 4 | true |

Con `can_invert: false`, `PrepPanel` deshabilita **«Validar CSV»** y **«Generar
paquete CSV»**. Es decir: **dentro de un mismo montaje el CSV corregido no podía
llegar nunca al backend**, y el único modo de reactivar el botón era irse a otra
pestaña — que lo reactivaba *porque destruía la corrección*. ⚠️ Sin arreglar esta
capa, la otra mitad de la fase habría sido **decorativa**: el corregido habría
sobrevivido, y el botón habría quedado apagado para siempre.

**El número del plan se sostiene; su referente no.** «25 parámetros» = `ContextoState`
(10) + `ParametrosState` (15), exacto. Pero **5 de esos 25 no tienen setter ni input
en todo el panel** (`inclinationDeg`, `declinationDeg`, `fieldIntensityNt`, `suscMin`,
`suscMax` — medido por la Fase 10 y escrito en `deshaciblePrep.ts:54-60`): son
constantes disfrazadas de estado y «sobrevivían» ya, porque renacían iguales. Lo que
el usuario perdía de verdad son **19 de los 25**. Y el total que se evaporaba es mucho
mayor: 1 (`PreparacionView`) + 17 (`PrepEnrichPanel`) + 43 (`PrepPanel`) = **61 campos**
en el núcleo siempre montado, 79 con los paneles auxiliares y 104 con el asistente y la
sala de mapas abiertos.

**Errata del propio expediente: «los archivos y el bbox sí sobreviven» es media
verdad.** `fileGravimetry` tiene **un solo escritor** (`PrepPanel.tsx:674`), así que eso
es cierto del flujo CLÁSICO. El flujo **PRINCIPAL** (`PrepEnrichPanel`, por donde entra
el usuario) guardaba `gravFile`/`magFile` en su propio reducer y no tocaba el store:
ahí se perdía **el archivo entero**, no sólo el mapeo.

**Dos consecuencias de NUEVO-2 que nadie había escrito, y que el gate ahora fija:**

1. **Un survey magnético quedaba en un callejón sin salida.** `fileMagnetometry` vive en
   el store y sobrevivía; `dataType` vivía en `contexto` y volvía a `"gravity"`. El botón
   de validar evalúa `!(dataType === "magnetic" ? fileMagnetometry : file)`: con sólo un
   CSV magnético cargado, al volver quedaba **apagado sin forma de encenderlo**.
2. **Y el archivo magnético se volvía invisible pero seguía viajando.** Su única señal en
   pantalla (`PrepPanel.tsx:1248`) está gateada por `dataType === "magnetic"`, mientras el
   paquete lo sigue metiendo (`:1111`). El usuario generaba un paquete conjunto creyendo
   que era gravimétrico.

**Qué sube al store y qué NO, con el criterio escrito.** Suben cuatro máquinas
(`contexto`, `parametros`, `avanzado`, `enriquecer`) y los sondajes confirmados —
5 campos nuevos de `AppState`, clasificados uno a uno en `store/deshacible.ts`.
**`operacion` (9 campos) se queda local a propósito**: son banderas de vuelo, errores y
mensajes. MEDIDO: **0 `AbortController`** en los tres paneles, así que un `loading`
superviviente sería un spinner eterno sobre una petición que ya se resolvió en el vacío;
y `packageMessage` se escribe **después** del `a.click()` que ya dejó el fichero en el
disco — restaurarlo afirma como presente un hecho del pasado. `csvValidation` no se
pierde: un efecto la recalcula al montar. Lo que sí sobrevive y sería mentira se apaga en
`despertarPreparacion()`: cargas en vuelo, errores viejos y **modales abiertos** (montan
componentes y relanzarían peticiones que nadie pidió).

**Hacer que el estado sobreviva OBLIGÓ a declarar su caducidad.** El flujo principal
**no tenía** `ARCHIVOS_CAMBIARON`: cambiar el CSV dejaba en pantalla la `ResultCard` del
anterior —con su `packageText` completo detrás de «Descargar»— y reenviaba su
`columnMap`. Hoy ese agujero dura una visita porque el desmontaje lo tapa por accidente;
esta fase quita el accidente, así que duraría la sesión. Se le añadió la transición que
le faltaba. **No es un extra: es la condición de la fase.**

**Un `useReducer` no es un store, y hay una diferencia que muerde.** El despacho lee el
estado **fresco** (`leer()`), no el del render: `resetOnFileChange` y el `onChange` de los
bounds despachan dos acciones seguidas a la misma máquina, y con el valor capturado la
segunda pisaría a la primera. React encolaba por nosotros. Efecto lateral bueno del
cambio: como `escribir` es una función de módulo, el `finally { GENERACION_TERMINADA }`
de una petición en vuelo **aterriza aunque el panel ya esté desmontado**.

**El historial de la Fase 13 perdió su premisa y se re-justificó, no se dejó como estaba.**
`useReducerConHistorial` borraba el historial al desmontar porque «el estado vuelve a su
inicial». Eso ya es falso. La razón que queda —y basta— es el APLICADOR: cierra sobre el
componente, y un delta sin dueño montado hace que `deshacerAmbito` borre la pila al primer
clic. Además la semilla del delta pasó a ser el estado **efectivo** y no el de fábrica: sin
ese cambio, volver a la pestaña habría grabado un comando espurio **cuyo `antes` son los
valores por defecto**, y un solo Ctrl+Z habría borrado todo el trabajo bajo la etiqueta
«Preset de densidad (+7)».

**Gate — las 4 preguntas.** *(1) ¿Existe?* 8 recorridos Playwright con el backend
sustituido en la frontera HTTP. *(2) ¿Mide los tres eslabones?* Sí, y el más duro es el
tercero: se **intercepta el `multipart/form-data`** de `/build-package`, se extrae el
adjunto `file` y se afirma sobre su CONTENIDO (`# Corrected gravity CSV` presente,
`gravity_mgal` ausente) y sobre `allow_g_raw` del query string — no sobre el nombre del
fichero ni sobre lo que se ve. *(3) ¿Discrimina?* El recorrido **G** es control negativo:
dar la vuelta sin tocar nada tiene que dejar los valores de fábrica. *(4) ¿Falla si se
rompe lo que dice defender?* **Verificado por mutación: 10/10**, cada una revirtiendo una
parte del arreglo, reconstruyendo y corriendo los 8 recorridos.

| # | Mutación | Recorridos que caen | Mensaje |
|---|---|---|---|
| M1 | `prepEnriquecer` no sobrevive | **B, H** | «✓ crudo.csv» no aparece |
| M2 | `prepParametros` no sobrevive | **A** | `Expected "4.5", Received "0.0"` |
| M2b | `prepContexto` no sobrevive | **A, F** | «Modo magnetometría» no aparece |
| M3 | el paquete usa `file` en vez de `correctedFile ?? file` | **C** | «el paquete NO lleva el CSV corregido» |
| M4 | `prepAvanzado` no sobrevive | **C** | la insignia «Correcciones aplicadas» no aparece |
| M5 | el CSV corregido no caduca con el archivo | **D** | «lleva el corregido del archivo ANTERIOR» |
| M6 | un campo de `AppState` sin clasificar | *(tipos)* | `tsc` TS2741 **y** `test_todo_campo_del_store_esta_clasificado` |
| M7 | el flujo principal no caduca su mapeo | **E** | la tarjeta de mapeo sigue en pantalla |
| M8 | `prepSondajes` no sobrevive | **H** | «+ sondajes (anclaje)» no aparece |
| M9 | el validador vuelve a ser ciego a la columna corregida | **C** | «Validar CSV» **deshabilitado** |

M3, M4 y M9 caen todas en el recorrido C y lo hacen con **tres mensajes distintos**, que es
lo que permite saber cuál de las tres causas se rompió.

🔴 **Y la mutación encontró un agujero en el propio gate, que se arregló antes de cerrar.**
En su primera versión el recorrido D comprobaba que la insignia «Correcciones aplicadas»
desaparecía al cambiar de archivo. Esa insignia la dibuja `correctionReport`, **no**
`correctedFile`: con M5 aplicada —el CSV corregido inmortal— los **8 recorridos salían en
verde** mientras el paquete viajaba con el corregido de OTRO archivo. Es el mismo defecto
que la fase persigue (dato que sobrevive y no se ve) con el signo cambiado. D pasó a mirar
el cable en vez de la pantalla.

**Acoplamiento declarado (regla del gate: si una mutación enciende más de lo previsto, se
dice).** M1 se predijo como «B y E» y salió **«B y H»**: el recorrido H afirma el rótulo
`+ sondajes (anclaje)`, que `PrepEnrichPanel` sólo dibuja si hay un archivo de origen
cargado — así que depende también de `prepEnriquecer`. Y E no depende de M1: su guardián es
M7, confirmado por separado. La predicción estaba mal; el gate, no.

**Regresión:** `tsc` 0 errores · `eslint` 0 errores (17 avisos preexistentes) ·
`next build` OK · **48/48 e2e** (los 40 previos + los 8 nuevos), incluidos los siete de la
Fase 13 que fijan el contrato *«la barrera borra la HISTORIA, no el estado»* y el de H-29
de la Fase 1 · **45/45** en las tres guardias de CI del backend que leen el frontend
(`test_fase13_undo_redo`, `test_fase10_contratos`, `test_fase9_camino_de_usuario`).

**Lo que esta fase NO hizo, y queda declarado:**
- **El historial de preparación sigue sin sobrevivir al cambio de pestaña.** El estado sí;
  el Ctrl+Z no. Es la misma semántica que la barrera de archivos y está escrita en
  `useReducerConHistorial.ts`. Hacerlo sobrevivir exige que el aplicador deje de depender
  del montaje, que es un cambio del historial y no del panel.
- **Los 16 campos del `GravityCorrectionWizard` y los 10 de `BoreholeUploadPanel` no se
  persisten.** Del asistente sobrevive su producto (el CSV corregido y su reporte), no su
  posición; de los sondajes sobreviven **los intervalos confirmados**, que son lo que viaja
  como anclaje y lo que se ve en dos rótulos distintos. La vista de detalle del panel de
  sondajes (tabla y mapa en planta) se reconstruye subiendo el fichero otra vez.
- **La tolerancia de duplicados de `parseCsvForValidation` sigue siendo `1.0`** sin unidad,
  y sus listas de columnas de posición no reconocen `lat_deg`/`lon_deg` (los que escribe el
  asistente). Es un AVISO, no un bloqueo, y la confusión metros/grados es anterior a esta
  fase: se midió y no se tocó.
- **`PrepEnrichPanel` y `PrepPanel` siguen teniendo archivos separados** — el mismo CSV hay
  que subirlo dos veces. Unificarlos es tentador y **hoy sería peligroso**: la caducidad de
  H-29 vive en los manejadores de `PrepPanel`, así que un archivo compartido cambiado desde
  el flujo principal dejaría vivos los reconocimientos de riesgo del anterior. Unificar los
  archivos obliga a unificar la caducidad, y es su propia fase.
- Nada de `H-36` ni `NUEVO-7`: son la Fase 25.

---

### FASE 25 (CERRADA) — Lo que el backend dice y el frontend no escucha · **S** · 🟠 P1 · *frontend* · H-36, NUEVO-7

**Dos huecos del mismo tipo**, y por eso van juntos: el backend publica algo y
el frontend no lo consume.

**NUEVO-7 — las `suggestions` del mapeo de columnas no llegan al usuario.** La
Fase 16 hizo que la ingesta caracterice los roles y **proponga** una corrección
cuando duda. Esa propuesta viaja en la respuesta y **ningún `.tsx` la lee**: 0
consumidores en TypeScript. Es decir, la parte cara de la Fase 16 —el criterio
que evita que un `X,Y,Z` entre torcido— está construida y muda. Cablearla es
mostrar la sugerencia en el panel de mapeo y dejar que el usuario la acepte.

**Y H-36 — «desactualizado» por tipos, no por lista:**

**Por qué va aquí.** La Fase 13 ya demostró en este repositorio que el
complemento exacto por tipos funciona: un campo sin clasificar **no compila**.
`resultIsStale` se quedó como lista a mano y la Fase 14 ya la dejó atrás — el
mismo agujero se repetirá con la fase siguiente si no se cierra por construcción.

**Trabajo.**
1. Convertir la lista de parámetros que invalidan el resultado en un tipo
   exhaustivo, con el patrón de `NO_DESHACIBLE`.
2. Incluir los parámetros de geología implícita de la Fase 14.

**Gate.** Añadir un parámetro nuevo al store **sin clasificarlo rompe el
typecheck**. Verificado añadiendo uno de mentira.

#### ✅ EJECUTADA — 2026-09-03

Frontend puro; el backend **no se tocó** (y no hacía falta: la parte cara ya
estaba construida en él). Guardia nueva: `e2e/fase25_backend_escuchado.spec.ts`
(9 recorridos, 4 de ellos sin navegador). Pieza nueva:
`componentes/prep/invalidaResultado.ts` (~310 l: la declaración y el constructor
de la huella). `PrepPanel.tsx` pierde el bloque de la huella; el efecto se muda a
`views/PreparacionView.tsx`.

**NUEVO-7 no era decorativo, y eso se comprobó ANTES de escribir código.** La
pregunta que podía tumbar media fase era: ¿llega la sugerencia por la ruta que
usa el frontend, y está el paso de mapeo en pantalla cuando llega? Las dos
respuestas son sí, y la segunda es **estructural, no empírica**: `suggestions`
sólo se calcula dentro de `if missing:` (`column_mapping_service.py:680-681`) y
`needs_mapping = bool(missing)` (`:663`), así que **es imposible tener
sugerencias con `needs_mapping` en false**. El selector del rol sugerido sale
además siempre en «— sin asignar —», porque `missing` son los requeridos que
`roles` no resolvió y `prefillMap` sólo rellena desde `plan.roles`: la sugerencia
es exactamente lo que llenaría ese hueco. Medido además en vivo con `TestClient`
sobre un CSV `X,Y,Z,Bouguer_mGal` — las dos rutas
(`/v2/gravity-import/analyze-columns` y `.../enrich-package`) devolvieron
`suggestions` con claves `x` e `y`.

**Dónde se pinta, y por qué ahí.** `suggestions` viene indexada **por rol**
(`Record<rol, {column, confidence, reason}>`), así que va DENTRO del selector de
ese rol y no en un cartel aparte: el dato útil es el valor que llenaría ese
desplegable, y el canal para escribirlo (`onChange` → `setField(role, v)`) ya
existía. Un cartel arriba habría obligado al usuario a traducir «rol y → columna
Y» y a buscar el selector correcto.

**Y se PROPONE, nunca se aplica sola.** El backend fija `confidence: "medium"` en
los tres sitios que construyen una sugerencia, y tiene un test que impide que sea
`"high"` («se propone, se confirma, no se aplica sola»,
`test_fase16_roles_de_columna.py:381-384`). Auto-rellenar el mapa habría
reabierto el defecto que la Fase 16 cerró —adivinar el rol de una columna— y por
eso hay una mutación dedicada a ese «arreglo» incorrecto (M2).

**H-36: la lista a mano ya se había quedado atrás, y por más de lo que decía la
ficha.** La ficha dice «no incluye parámetros de Fase 14». Al contrastar las 23
entradas contra lo que `handleGeneratePackage` mete de verdad en el `config_json`
aparecieron **cinco** ausencias, no una:

| Ausente de la lista vieja | A dónde viaja | Por qué duele |
|---|---|---|
| `implicitGeologyParams` | `config.implicit_geology` | **La que el plan nombra** (Fase 14): mueve el `m_ref` del smallness |
| `acknowledgeSpatialRisk` | `config.acknowledge_spatial_risk` | Es un **gate** del backend: sin él se rechaza, con él entra |
| `acknowledgeRegionalScale` | `config.acknowledge_regional_scale` | Ídem |
| `correctedFile` | el fichero **primario** + fuerza `allow_g_raw` | Cambiar de archivo sí avisa (`clearActiveRun`); aplicar correcciones **no pasaba por ahí** |
| `prepSondajes` | `boreholes_json` | Es el **anclaje**, y la fuente de litologías del prior implícito |

`correctedFile` es el más caro: no es un parámetro, **es el dato de entrada**.
Sustituía el CSV bajo un modelo que seguía en pantalla, y además el valor
efectivo de `allow_g_raw` cambiaba sin que la entrada `allowGRaw` de la lista se
moviera.

🔴 **Y una sexta ausencia que no era una entrada sino un panel entero.**
`markResultStale()` tenía **UN solo llamador en todo el frontend**: `PrepPanel`,
el flujo CLÁSICO, el que vive colapsado bajo «Avanzado». El flujo **PRINCIPAL**
—`PrepEnrichPanel`, por donde entra el usuario— no tenía huella **ninguna**, y
seis de sus campos viajan al backend en cada generación (`utmZone`,
`gravimeterType`, `surveyDate`, `useHelmert`, `ctrlPoints`, `columnMap`). Cerrar
H-36 sólo donde estaba escrito habría dejado el tipo exhaustivo sobre la mitad
que casi nadie toca. Por eso el efecto se muda a `PreparacionView`: es el padre
común de los dos paneles, está montado siempre que cualquiera de los dos puede
cambiar (`<details>` colapsa, no desmonta) y desde la Fase 24 puede leer el
estado entero del store sin pasar por ningún panel.

**Dos entradas de la lista vieja eran ruido, y se declaran como tales en vez de
retirarse.** `latSouth` y `lonEast` **no viajan**: sólo alimentan
`validateCoords()`; al backend va únicamente la esquina NO (`lat`=`latNorth`,
`lon`=`lonWest`). Se quedan declaradas, con el motivo escrito: `validateCoords()`
exige las cuatro esquinas o ninguna, así que media caja cambiada es una caja
distinta. **Marcar de más avisa sin motivo; marcar de menos calla con motivo.**

**Lo que sí se afinó, porque un aviso que salta sin causa se aprende a ignorar.**
Se midió que `pgiParams` y `remanenceParams` sólo viajan si están `enabled`, y
que `ctrlPoints` sólo viaja con `useHelmert`. Antes, mover el `alpha_pgi` con el
PGI apagado marcaba el resultado como desactualizado **sin que nada saliera del
navegador**. El descriptor admite una `huella` que recibe también el estado de su
máquina, y esos tres casos la usan. Residuo declarado y NO cerrado: el paquete
exige además `pkgDataType === "magnetic"` para la remanencia, y eso depende de
qué ficheros hay y no de esa máquina — con gravimetría sola sigue marcando de más.

**Gate — las 4 preguntas.** *(1) ¿Existe?* 9 recorridos: 5 en Playwright con el
backend sustituido en la frontera HTTP + 4 sin navegador que importan la
declaración. *(2) ¿Mide los tres eslabones?* Sí. La afirmación más dura del
recorrido A no es que el texto aparezca sino que **lo aceptado VIAJA**: se
intercepta el `multipart/form-data` de `/enrich-package` y se lee
`column_map_json`. *(3) ¿Discrimina?* Dos controles negativos: A2 afirma que el
desplegable **sigue vacío** hasta que el usuario acepta, y B2 que **dar la vuelta
sin tocar nada** no marca nada — que importa porque `despertarPreparacion()`
ESCRIBE en el store al volver a la pestaña. *(4) ¿Falla si se rompe lo que dice
defender?* **Verificado por mutación: 6/6.**

| # | Mutación | Recorridos que caen | Mensaje |
|---|---|---|---|
| M1 | la sugerencia deja de bajar a `RoleSelect` | **A1, A2, A3** | `toBeVisible()` sobre `role-suggestion-x` |
| M2 | la sugerencia se **auto-aplica** en `prefillMap` | **A1, A2, A3** | A2: `toHaveValue("")` recibe `"X"` |
| M3 | el flujo principal vuelve a no tener huella | **B1, C1** | C1: «debería invalidar: `enriquecer.utmZone`» |
| M4 | `huellaPrevia` no arranca con la huella del 1.er render | **B2** | `toHaveCount(0)` recibe `1` |
| M5 | `implicitGeologyParams` reclasificado a `NO_INVALIDA` | **C1, C4** | «debería invalidar: AUSENTE `implicitGeologyParams`» |
| M6 | `prepSondajes` se compara por `.length` | **C3** | el sondaje corregido no mueve la huella |
| M7 | un campo de máquina sin clasificar | *(tipos)* | `tsc` **TS2741** en `invalidaResultado.ts` |

M7 se verificó **cuatro veces**, una por máquina (`ContextoState` → línea 80,
`ParametrosState` → 120, `AvanzadoState` → 158, `EnriquecerState` → 230), y cada
una señala la línea exacta del complemento que falta.

🔴 **La mutación encontró DOS agujeros en el propio gate, arreglados antes de
cerrar.**

1. **La huella de `prepSondajes` contaba intervalos.** En su primera versión era
   `v => v.length`, que es más barato y está **mal**: el caso interesante es
   justo re-subir el mismo sondaje con densidades o litologías corregidas —
   mismo número de filas, otro anclaje y otro prior implícito. M6 revive ese
   fallo y C3 es la afirmación que lo caza.
2. **El recorrido B1 moría por TIMEOUT y no por aserción.** Aislado pasaba en
   ~55 s; encadenado con B2 reventaba los 60 s por defecto. Un rojo por timeout
   no dice nada del código y **contaminó de hecho la lectura de M4**: hubo que
   correr B1 aislado para ver que M4 sólo tumba B2. Se declaró `test.slow()` en
   vez de recortar el recorrido — cargar el modelo por la vía real es lo que hace
   que el aviso signifique algo.

**El límite honesto del tipo, escrito porque es fácil creer lo contrario.** El
complemento exacto obliga a **clasificar** cada parámetro; no acierta por ti la
clasificación. Mover una clave de `*_INVALIDA` a `*_NO_INVALIDA` **compila igual
de bien** — M5 lo demuestra: `tsc` salió 0 y quien la cazó fue la tabla del
recorrido C, no el compilador. Por eso esa tabla es una **lista explícita** y no
un recorrido de las declaraciones: derivarla de lo declarado la haría pasar
siempre.

**Números.** 23 entradas a mano → **34 parámetros declarados** (7 contexto + 12
parámetros + 4 avanzado + 6 enriquecer + 5 store), y su complemento escrito uno a
uno: 24 motivos de exclusión (3 + 3 + 5 + 11 + 2).

**Regresión:** `tsc` 0 errores · `eslint` 0 errores sobre lo tocado ·
`next build` OK · **9/9** en el recorrido nuevo · y el e2e de la Fase 1 que fija
este mismo aviso desde el flujo CLÁSICO (`fase1_confianza.spec.ts:282`, mueve
`densityMin`) sigue verde, que es lo que confirma que mudar el efecto a
`PreparacionView` no rompió el camino que ya existía.

**Lo que esta fase NO hizo, y queda declarado:**
- **`role_confidence` sigue sin pintarse.** El plan lo publica por rol
  (`role_confidence: Record<string, string>`) y ningún `.tsx` lo lee. Es el
  hermano natural de `suggestions` y viviría en el mismo sitio (`RoleSelect`),
  pero **no es NUEVO-7** y meterlo habría ensanchado la fase por parecido.
- **El mensaje del backend nombra un campo que en esa rama está siempre vacío.**
  `gravity_import_api.py:1444` dice «ver 'suspicions'/'suggestions'», y ese texto
  sólo se emite cuando `_needs_conf` es true, o sea cuando `needs_mapping` es
  **false**, o sea cuando `missing` está vacío — y entonces `suggestions` es `{}`
  por construcción. Errata de redacción, sin efecto sobre el usuario, y **de
  backend**: esta fase es *frontend* y la Regla de Oro no se salta por una cadena
  de texto. Queda anotada.
- **La remanencia sigue marcando de más con gravimetría sola** (residuo medido,
  arriba).
- **`PrepEnrichPanel` y `PrepPanel` siguen teniendo archivos separados**: sigue
  siendo la deuda que declaró la Fase 24, y sigue sin dueño.

---

### FASE 26 (CERRADA) — Que la señal informe, antes de tocar el techo · **L** · 🟠 P1 · *backend, medir* · ACAD-10

**Por qué existe esta fase.** Es el problema más grande del producto y **no estaba en el plan**. Tu
propio hallazgo lo midió con 99 inversiones por la ruta de producción
(`validation/HALLAZGO_2026-08-06_techo_medium.md`):

- En el régimen donde el producto declara su fortaleza, **1 de cada 3 realizaciones de ruido** da un
  blanco desplazado **~170 m en vez de ~19 m**.
- Y TerraQuantum **no puede distinguir los dos casos**: Spearman(chi2_red, PR-AUC) = **+0,073** sobre
  75 corridas; controlando por régimen, la **mediana de ρ es exactamente 0,000**.
- El caso más claro: mismo mundo, mismo survey, misma λ, sólo cambia la semilla, y los
  diagnósticos salen **idénticos** con resultados que difieren 10×.

Mientras eso siga así, la escala de confianza no comunica «confianza media»: comunica **«no tengo
forma de decirte»**. Y es lo que impide vender targeting con barras de error.

**Trabajo** — las direcciones ya están escritas en el §4 del hallazgo, en orden de coste:
1. **Cambiar la longitud de onda del examen**: en vez de alternar celda a celda, usar **bloques del
   tamaño del objetivo declarado**. Convierte la pregunta en «¿resuelve este survey un cuerpo del
   tamaño que digo buscar?», que **sí varía entre surveys**. El checkerboard actual devuelve el mismo
   número siempre, **por diseño y no por avería**.
2. Recalibrar el umbral contra lo que un buen survey gravimétrico **realmente** alcanza. Si el mejor
   caso posible da 0,3, un PASS en 0,6 no clasifica: rechaza.
3. Separar «resolución de estructura fina» de «confianza en el blanco». El propio comentario del
   código (`geophysics_service.py:874-876`) reconoce que el targeting horizontal puede ser bueno con
   resolución fina pobre, y aun así aplica el cap.
4. Hacer informativo el detector de null-space para el caso frecuente (smear profundo
   data-consistente), no sólo para la saturación total.
5. **Barrer semillas** en tests y benchmarks. Hoy usan semilla fija, y una semilla no es una muestra.

**Gate.** El gate es **un número, no un parche**: Spearman entre el diagnóstico nuevo y PR-AUC sobre
**≥75 corridas en ≥5 regímenes**. Si no sube claramente por encima del **0,073** actual, la fase
**no cierra** y el techo se queda donde está.

#### ✅ EJECUTADA — 2026-09-03

Backend puro; el frontend **no se tocó** (y hay consecuencia: ver el riesgo al final).
Registro completo con todas las tablas:
[`validation/HALLAZGO_2026-09-03_resolucion_informativa.md`](../validation/HALLAZGO_2026-09-03_resolucion_informativa.md).

**El diagnóstico del plan era correcto pero incompleto, y el trabajo que pedía habría
sido insuficiente.** La dirección 1 —cambiar la longitud de onda— es real, pero al
medirla contra el código resultó ser **la menor de tres causas independientes**, y por sí
sola no acerca el examen al aprobado:

| bloque del tablero | 1 celda (hoy) | 2 celdas | 3 celdas | 4 celdas | umbral de PASS |
|---|---:|---:|---:|---:|---:|
| `pearson_r` | **0,116** | 0,212 | 0,192 | 0,247 | **0,60** |

Las otras dos, que nadie había medido:

- **Puntúa profundidades que ningún survey gravimétrico resuelve.** El Pearson se calcula
  sobre la malla entera, incluidas capas donde la recuperación es ~0 para cualquier
  survey: un survey perfecto tampoco aprobaría. Mismo kernel, misma λ, mismo tablero —
  puntuado sólo dentro de la banda 0–250 m con bloques de 750 m: **r = 0,704**. El examen
  no medía este survey; medía el promedio entre lo resoluble y lo que nunca lo será.
- **Califica a un solver distinto del que produce el modelo.** El QA invierte con
  `lsqr(damp=λ)` sobre el kernel Core: sin padding, sin bounds, sin depth-weighting. Con
  **el mismo dato observado** y 17 semillas, ese solver devuelve PR-AUC **0,039–0,041** y
  el centroide a ~85 m donde producción devuelve **0,583–1,000** y ~466 m. Aunque
  aprobara, no describiría el modelo que el usuario está mirando.

**Lo que se construyó.** `services/resolution_qa.py` (nuevo, ~300 l): un **perfil de
resolución** por banda de profundidad × escalera de tamaños de bloque lateral, escalado a
la amplitud de **señal** (`sqrt(rms_obs² − σ²)`) y con el σ **declarado**, puntuado sobre
el **mapa en planta**. Sale una **longitud de resolución en metros** por banda —«este
survey resuelve bloques de 250 m arriba, 500 m hasta 750 m, y nada más abajo»— que el
usuario compara con el tamaño del cuerpo que busca. Cuesta **0,85 s** en una corrida de
~30 s (2,8 %), porque cada LSQR del examen son 8 ms.

**El gate, con dos listones en vez de uno.** El 0,073 del plan es ρ(`chi2_red`, PR-AUC).
Al re-medirlo salió que **el tablero de hoy ya da ρ = +0,275** sobre esas mismas 75
corridas: superar 0,073 era demasiado fácil, así que el diagnóstico nuevo se comparó
contra los dos.

| diagnóstico | ρ vs PR-AUC (74 corridas de selección) | ρ (15 medianas por régimen) |
|---|---:|---:|
| `chi2_red` — el control del plan | +0,0601 | +0,1479 |
| tablero de hoy | +0,2747 | +0,3381 |
| **`resolvability_index`** | **+0,8746** | **+0,9324** |

**Y el conjunto de CONFIRMACIÓN — 75 corridas, 15 regímenes, 5 semillas frescas (EL GATE):**

| diagnóstico | ρ vs PR-AUC (75 corridas) | ρ **DENTRO** de régimen (mediana) |
|---|---:|---:|
| `chi2_red` — el control del plan | **−0,0675** | −0,100 |
| tablero de hoy | +0,1996 | — |
| `misfit_pct` (negado) | +0,3564 | — |
| **`resolvability_index`** | **+0,8081** | +0,200 |
| `floor_mass_excess` (negado) | +0,6523 | **+0,7071** |

**GATE PASADO.** +0,8081 contra el 0,073 del plan y contra el +0,275 del tablero. El
número encoge respecto al conjunto de selección (+0,8746 → +0,8081), que es exactamente lo
que debe pasar cuando el diseño se eligió en otro sitio; sigue siendo un orden de magnitud
por encima del listón. En este conjunto `chi2_red` sale **negativo**.

**El escalar primario NO es el mejor que se midió, a propósito.** Variantes con una banda
o un peldaño escogidos llegaban a **+0,9173**; se descartaron porque la ganancia son tres
centésimas y el coste es un parámetro elegido mirando la respuesta. El índice es la media
de **todo** el examen y no tiene ninguno. Y como el diseño se eligió mirando datos, el
número del gate se mide en un conjunto de **confirmación** con 5 semillas frescas y los
dos escalares **pre-registrados** en `validation/exp_resolution.py`.

**La otra mitad del hallazgo también se cerró, y el dato ya estaba en la casa.** El perfil
no puede distinguir realizaciones de ruido —usa σ, no la muestra—, así que la pregunta
seguía abierta: ¿qué separa, con el survey FIJO, la corrida de 5,6 m de la de 285,5 m?
Midiendo 13 candidatos derivados del modelo recuperado, uno lo hace:

| candidato | ρ agrupado | ρ **DENTRO** de régimen (mediana) |
|---|---:|---:|
| `chi2_red` | +0,038 | **+0,000** |
| **masa en la banda de piso** (negado) | +0,677 | **+0,741** |

`floor_mass_excess` = anomalía en la banda de piso ÷ la que pondría ahí un modelo
uniforme (contada en celdas). En `baseline`, mismo mundo y misma λ: 0,065 / 0,125 / 0,329
en las tres que aciertan y **0,944** en la que se va a 285 m — un factor 14×, donde
`chi2_red` variaba un 16 % sin orden. **Cierra la dirección 4:** `is_null_space_artifact`
exige saturación TOTAL al bound y salió `False` en 75 de 75, incluidas las 15 con PR-AUC ≤
0,01 donde el modelo *es* smear.

**Un callejón sin salida que vale registrar.** La primera versión leía el perfil en la
banda del blanco recuperado. `best_target.depth_m` sale **62,5 o 187,5 m en las 74
corridas** —con el cuerpo a 250, 400, 600 o 900 m— y cae **más somero cuanto más profundo
está el cuerpo** (900 m → 62,5 m en 5 de 5): anclar ahí le daría a las corridas **peores**
el examen **más fácil**. Sobreconfianza fabricada. El resumen final es agnóstico de
profundidad a propósito.

**Dirección 5 — una semilla no es una muestra.** `tests/seed_sweep.py` (nuevo) y los tres
benchmarks científicos (`checkerboard`, `two_body`, `dipping_dike`) pasan de afirmar sobre
`default_rng(42)` a afirmar sobre la **mediana de N semillas declaradas**, publicando
**todas** en el mensaje de fallo. `TQ_BENCH_SEEDS` sube N sin tocar código.
`exploration/checkerboard_test.py` recibe `--seed`.

**El veredicto.** El tablero **deja de topear** y queda publicado como control histórico
(`role: historical_control_since_fase26`) — su constancia es la evidencia del techo.
Entran dos señales medidas: `survey_resolution` (LOW si el examen no resuelve **nada**: esa
clase son 20 corridas con PR-AUC **máximo 0,186** frente a 0,644 del resto, y **10 de las
20 salían hoy MEDIUM**) y `best_target_floor_smear`.

**`HIGH` sigue retenido, y ahora se dice por qué.** No lo topa ya un examen imposible: lo
topa `high_hold_pending_fase30`, con `structural: false` y condición de salida escrita. Es
lo que el plan ordena y lo que el hallazgo de agosto exige por escrito («primero que la
señal informe, después subir el techo»), y sigue siendo prudente: `floor_mass_excess` caza
27 de 49 desplomes, no los 49.

**Verificado por mutación (la pregunta 4).** 5 mutaciones en `tests/test_f26_resolution_qa.py`
—volver a puntuar toda la malla, volver al tablero celda a celda, ignorar el ruido, poner
un umbral plano al smear de piso, y un índice constante— más 2 mutaciones sobre los
benchmarks con semillas (λ absurdo y centroide del cuerpo equivocado), que se pusieron
**rojas** publicando cada semilla y se restauraron con hash verificado. **22/22** en el
archivo nuevo y **81/81** en el conjunto de veredicto/reporte.

**Erratas del expediente, medidas de paso.** El hallazgo de agosto atribuía el techo a la
longitud de onda: es **una** de tres causas y la menos importante. Y su §4 proponía
«recalibrar el umbral»: lo medido dice que el umbral de 0,60 **no había que bajarlo** —
había que hacer el examen respondible; con el examen nuevo un survey sano lo pasa (0,70–0,79)
y uno degradado no (0,03).

**Riesgo abierto — NUEVO-10.** `resolution_qa`, `floor_mass_excess` y el bloque `ceiling`
**entero** no los lee ningún `.tsx`: `HonestReportWidgets.tsx:50` consume `overall_verdict`
pero sólo `level` y `limiting_factors`, y `RecoveryCoverageWidgets.tsx:135` sigue leyendo
`checkerboard_qa`. La UI mostrará el literal `high_hold_pending_fase30` sin explicación.
Misma familia que NUEVO-7/H-36 de la Fase 25; **no se toca aquí** porque la regla del
proyecto prohíbe backend y frontend en la misma fase.

---

### FASE 27 (CERRADA) — El instalador falla en voz alta cuando falta una dependencia · **M** · 🟡 P2 · *empaque* · NUEVO-4, NUEVO-5, H-23

**Por qué va aquí.** La Fase 2 hizo que el **arranque** fallara en voz alta. El
**build** todavía falla en silencio. No es hipotético: en esta máquina el
`python` del PATH es **3.11.9 sin numpy**, mientras `.python-version` declara
3.14.4 (y `py -3.14` sí tiene numpy 2.4.4).

**Trabajo.**
1. Que `_safe_submodules` avise —o aborte— en vez de devolver `[]`
   (`terraquantum_backend.spec:21-25`).
2. Añadir a `scripts/build_desktop.ps1` la comprobación del intérprete contra
   `.python-version`, igual que ya hace con PyInstaller.
3. Generar un lockfile con hashes (`pip-compile --generate-hashes`) e instalar
   con `--require-hashes` en CI y en el build.
4. Pinear `six`.

**Gate.** Construir con una dependencia deliberadamente ausente y exigir que el
build **falle**. Hoy pasa y produce un instalador roto.

#### ✅ EJECUTADA — 2026-09-03

Empaque puro. **NUEVO-4, NUEVO-5 y H-23 cerrados.** El frontend no se tocó y el
código de la aplicación tampoco: los cambios son el `.spec`, el script de build,
`requirements.txt`, un lockfile nuevo, dos scripts de CI y la CI.

**El punto 1 del plan, tal como está escrito, no habría arreglado nada.** La
ficha de NUEVO-4 culpa al `except Exception` del `.spec` («traga la excepción»).
Medido contra el código: **no hay excepción que tragar**. `collect_submodules`
devuelve `[]` por su cuenta cuando el paquete falta —está en su propio fuente,
`if not is_package(pkg): … return []`— y sólo deja un log de nivel **DEBUG**, que
el `--log-level WARN` del build ni siquiera imprime. Los tres modos de fallo,
medidos uno a uno:

| situación del paquete | qué hace `collect_submodules` |
|---|---|
| ausente del entorno | **devuelve `[]`** — no lanza |
| presente pero roto | **devuelve `[]`** — no lanza |
| presente y no escaneable | **devuelve `[pkg]`** — no lanza |

Hacer que `_safe_submodules` propagara la excepción habría dejado el defecto
exactamente donde estaba. Lo que defiende es comprobar el **resultado**, y hay
que cubrir **dos** formas de fallo, no una: `[]` y `[pkg]` a secas.

**La medida ANTES/DESPUÉS, mismo entorno (`omf` bloqueado en `sys.meta_path`):**

| | aborta | `hiddenimports` | de `omf` |
|---|---|---:|---:|
| spec de HEAD | **NO** | 1.481 | **1** (`['omf']`, cero submódulos) |
| spec de la Fase 27 | **SÍ** | — | — |

Con `omf` sano son **10** submódulos (`omf.base`, `omf.data`, `omf.fileio`…).
El instalador salía con el nombre del paquete y sin nada dentro.

**GATE PASADO, con el comando real.** No con un arnés:
`py -3.14 -m PyInstaller terraquantum_backend.spec --noconfirm --log-level WARN`
con `omf` ausente ⇒ **exit 1 en 10 s**, con el paquete, el intérprete y el comando
de arreglo en el mensaje. Antes ese mismo comando seguía hasta producir el exe.

**El intérprete (H-23).** `build_desktop.ps1` llamaba a `python` a secas y nunca
lo comparaba con `.python-version`. Confirmado en esta máquina: el `python` del
PATH es **3.11.9 y no tiene numpy, ni scipy, ni omf — le faltan los 105
paquetes**; `py -3.14` los tiene. Ahora el script **resuelve** el intérprete que
declara `.python-version` (medido: elige `py -3.14`, y si el fichero dijera
`3.11.9` elegiría `py -3.11`), aborta si el mayor.menor no coincide y avisa si
sólo difiere el parche.

**El lockfile (H-23).** `requirements.lock`: **105 paquetes** pineados exactos con
el sha256 de **todos** los ficheros publicados de cada versión, instalable con
`--require-hashes` en la CI y en el build. Se generó **sin instalar nada nuevo**:
el plan pedía `pip-compile` (pip-tools), que es una dependencia y la regla del
proyecto exige permiso; `scripts/ci/gen_lockfile.py` hace lo mismo con la
biblioteca estándar (pip resuelve en `--dry-run`, PyPI aporta los hashes).

Verificado, no supuesto:
- instala en **Windows/cp314** y en **Linux/manylinux/cp314** — el conjunto
  resuelto es **idéntico en las dos** (105 paquetes, mismas versiones, cero
  diferencias), así que el lock no necesita marcadores de entorno;
- **control negativo**: con los hashes de `six` corrompidos, pip **rechaza** con
  *«THESE PACKAGES DO NOT MATCH THE HASHES»* y exit 1. Ojo con el primer intento
  —corrompí **uno** de los dos hashes y pip usó legítimamente el otro fichero y
  salió en verde: el control sólo vale corrompiendo **todos** los de un paquete.

**NUEVO-5.** `six==1.17.0` pineada. Lo declaran `omf` (**sin ningún
especificador**) y `properties` (`>=1.7.3`). Y se añade el invariante que faltaba:
un test lee las dependencias de `omf` desde sus metadatos y exige que **las
cuatro** estén pineadas, para que la lista del comentario no vuelva a
desincronizarse del código.

**Un hallazgo de propina que prueba que el mecanismo ya escondía algo.**
`email_validator` llevaba en la lista de recolección del `.spec` **sin estar
instalado, sin estar en `requirements.txt` y sin un solo `EmailStr` en el
backend**. Aportaba `[]` en cada build desde la Fase 7 y nadie se enteró — que es
literalmente el defecto que esta fase cierra. Retirado.

**Y un defecto de la misma familia que nadie había mirado:** los siete paquetes
**de la propia aplicación** (`api`, `services`, `core`…) sólo se recolectan si su
carpeta está en `sys.path`, cosa que dependía del *cwd* del build. Lanzado desde
otro directorio, el exe salía sin los **121 submódulos de la app** — en silencio,
igual que todo lo demás. El spec ahora ancla `SPECPATH`.

**Verificado por mutación (la pregunta 4). 17/17.** 17 mutaciones sobre los cinco
artefactos —reponer el `return []`, quitar la guarda de `[pkg]`, no mirar los
data files, no mirar el IGRF, no comprobar la instalación, reponer
`email_validator`, quitar el pin de `six`, mover el núcleo numérico, dejar un
paquete sin hash, perder un requisito del lock, volver a `python -m PyInstaller`,
dejar de comprobar el entorno, detectar el intérprete y no abortar, y cuatro
sobre las decisiones del comprobador— todas **rojas**, restauración verificada
por hash.

**Y el gate se cazó a sí mismo un agujero, que es el motivo de tener el gate.**
La mutación «que una dependencia ausente deje de ser fatal» salió **VERDE** en la
primera pasada: los tests probaban la función que **clasifica** y ninguno probaba
la **decisión** —el código de salida, que es lo único que el build mira—, porque
en esta máquina no falta nada y esa rama no se ejecutaba nunca. Se añadieron
`--lock`/`--requirements` al comprobador para poder ejercitarla contra un lock
preparado. Una segunda mutación («que un lock inexistente pase por bueno»)
también escapó: seguía abortando, pero con un *traceback* en vez del aviso con el
comando de arreglo. Las dos están cazadas ahora.

**Errata del expediente, medida de paso.** La ficha de NUEVO-4 dice que
`build_desktop.ps1` «nunca instala ni verifica `requirements.txt`». Cierto, pero
lo relevante es lo otro: aunque lo verificara, el `.spec` habría seguido
recolectando en silencio. El defecto vivía en el `.spec`, no en el script.

**Una puerta de CI que llevaba en rojo desde la Fase 26.** Al medir el gate salió
que `tests/test_fase5_superficie_config.py` fallaba en `main`: la Fase 26 añadió
`TQ_BENCH_SEEDS` (`tests/seed_sweep.py`) y no la declaró en el inventario de
superficie de configuración. Declarada aquí. Es la tercera vez que aparece este
patrón (Fase 3, Fase 15).

**Lo que NO se hizo, y por qué.** (1) El script **no instala** dependencias por su
cuenta: comprueba y aborta con el comando exacto, y sólo instala con
`-InstallDeps`. Un script de build que modifica en silencio el Python del usuario
es justo lo que la regla del proyecto prohíbe. (2) No se corrió un build completo
del instalador: el gate es el caso de FALLO y ése sí se corrió con el comando
real; del camino sano se verificó que el spec evalúa entero con los recolectores
de verdad (1.481 *hiddenimports*) y que PyInstaller resuelve los **1.343** data
files sin ninguna fuente inexistente, con el IGRF en el mismo destino que antes.

**Riesgo abierto — NUEVO-11.** El lock es **reproducible**, pero no es el entorno
donde se validó la física. Medido: **37 de los 105** paquetes están instalados
aquí en otra versión —entre ellos `protobuf 5.29.6` frente a `6.33.6` (un major),
`cryptography 46.0.7` frente a `50.0.1` (cuatro) y `zarr 3.2.1` frente a `3.3.0`—
y `pip check` señala una incoherencia ya existente (`google-cloud-storage 3.10.1`
pide `google-api-core>=2.27.0`, hay 2.25.2). Ninguno es del núcleo numérico
(`numpy`/`scipy`/`pyproj`/`polars` coinciden exactos, y un test lo vigila), así
que la física no se mueve. Esto **no empeora** nada —la CI ya resolvía fresco en
cada corrida, que es como `zarr` derivó— pero cuantifica por primera vez el
«riesgo residual medido» que `docs/06` declaraba sin número. Reconciliarlo exige
instalar dependencias, que necesita permiso expreso; por eso el comprobador trata
la ausencia como **fatal** y la deriva dentro de rango como **aviso**.

**Riesgo abierto — NUEVO-12.** El mismo defecto que esta fase cierra en el build
sigue vivo en `check.ps1`, la puerta que se corre **antes del push**: llama a
`python` a secas. Medido con el `python` del PATH (3.11.9), `deps_closure.py`
sale **exit 1** por falta de metadatos — una **falsa alarma**, que es la forma más
rápida de que un gate acabe desactivado. No se toca aquí porque el plan acota la
Fase 27 al `.spec`, a `build_desktop.ps1`, al lock y a `six`; el arreglo es el
mismo patrón de resolución de intérprete y cabe en la Fase 29.

---

### FASE 28 (CERRADA) — El updater: o apunta bien, o se retira · **M** · 🟡 P2 · *empaque* · H-20

**Por qué va aquí.** Hoy es un mecanismo de papel con un agravante: el mensaje de
error le sugiere al usuario que quizá no tiene internet, cuando la causa real es
que la URL apunta a un repositorio ajeno. Prometer una comprobación que siempre
falla es peor que no ofrecerla.

**Trabajo.**
1. Corregir el endpoint al remoto real y publicar `latest.json` firmado desde un
   workflow de release; **o**
2. Retirar el bloque `updater` de `tauri.conf.json` y el ítem de menú hasta que
   exista.
3. Si se queda como aviso manual, que el texto lo diga en vez de prometer
   instalación.

**Gate.** Con red disponible, «Buscar actualizaciones» distingue **tres** estados
—al día / hay versión nueva / no se pudo comprobar— y no confunde el tercero con
los otros dos.

#### ✅ EJECUTADA — 2026-09-06

Empaque puro. **H-20 cerrado.** El backend no se tocó; los cambios son el shell
de Tauri (`lib.rs`, `tauri.conf.json`, `splash/index.html`), un gate nuevo, un
generador de manifiestos, el workflow de release, la CI y `check.ps1`.

**El gate del plan ya pasaba antes de tocar nada, y el defecto era real.** Pedía
que el aviso «distinga tres estados y no confunda el tercero con los otros dos».
Medido contra HEAD: el payload de error llevaba `state:"error"`, distinto de
`"current"` y `"available"`. Literalmente, verde. Lo que fallaba era otra cosa:
**dos de los tres estados eran INALCANZABLES y el único alcanzable mentía sobre
su causa.** Es la cuarta fase seguida en la que el listón del plan mide algo más
pequeño que el defecto.

**Las dos erratas de la ficha, medidas.** (1) H-20 dice «repositorio
inexistente». `api.github.com/users/TerraQuantum` devuelve **200**: es la cuenta
de un **tercero real** (id 90737998). Lo que impedía que un release ajeno se
instalara no era la URL sino la **firma minisign** — la defensa funcionando como
se diseñó. (2) La ficha da a entender que el fallo es indistinguible de la falta
de red. No lo es: `updater.rs:483-530` muestra que un status no exitoso **no
guarda error** y termina en `Error::ReleaseNotFound`, mientras la falta de red da
`Error::Reqwest`. **La información para no mentir ya estaba ahí y se tiraba.**

**Lo que veía el usuario, reconstruido literalmente** (internet sano, HTTP 404):

> «No se pudo comprobar si hay actualizaciones.» / «*Could not fetch a valid
> release JSON from the remote*. Si no tienes internet es lo esperable…»

El `Display` del crate **en inglés**, incrustado en una frase en español, con una
atribución de causa falsa. `docs/02` §4.1 exige «error en español del catálogo
con acción sugerida»: fallaban las tres cosas.

**Lo medido el 2026-09-05**, que es lo que decide la fase:

| consulta | resultado |
|---|---|
| endpoint que había (`TerraQuantum/terraquantum`) | **HTTP 404** |
| endpoint del remoto real | **HTTP 404** |
| `api.github.com/repos/Martincancino/TerraQuantum-Engine` | **404** sin autenticar… |
| `git ls-remote --heads origin` | …pero **sí** lista `main` ⇒ el repo **existe y es PRIVADO** |
| `git ls-remote --tags origin` | **vacío** ⇒ cero releases |
| `api.github.com/users/Martincancino/repos` | **`[]`** ⇒ cero repos públicos |

**Por eso la opción 1 del plan, tal como está escrita, no se puede ejecutar.**
«Corregir el endpoint al remoto real y publicar `latest.json`» no habría cambiado
NADA observable: los *assets* de un repositorio privado no son descargables sin
autenticación y el updater consulta sin credenciales, así que el 404 seguiría
igual para todos los usuarios **después** de publicar. Y la opción 2 —retirarlo—
habría destruido el trabajo de la Fase 2 y dejado el gate sin sujeto.

**Lo que se hizo, que es la opción 3 llevada hasta el final:** el endpoint deja
de apuntar a un tercero, y el aviso pasa de tres estados (uno alcanzable) a
**cinco desenlaces** con causa, código y acción propios —
`UPDATE_DISPONIBLE`, `UPDATE_AL_DIA`, `UPDATE_SIN_PUBLICAR`, `UPDATE_SIN_RED`,
`UPDATE_MAL_CONFIGURADO`. El estado honesto de hoy es `UPDATE_SIN_PUBLICAR`:
«todavía no se ha publicado ninguna versión», y **tiene prohibido mencionar
internet** porque el servidor acaba de contestar. Hay un test que lo exige.
Los avisos llevan ahora `hint` y `code`, como los errores de arranque desde H-17.

**Un defecto de la misma familia, encontrado al medir: `check()` no tenía tope de
tiempo.** La ruta Rust nunca llama a `.timeout()` y reqwest no pone ninguno por
defecto, así que una red que acepta la conexión y luego calla dejaba la ventana
en «Consultando…» **para siempre**. Es H-17 —el splash infinito— en otra ventana,
un año después y en otro fichero. Tope de 15 s.

**Y una puerta que no corría, la cuarta vez que aparece el patrón.** Los **9
tests de Rust** que defienden H-17/H-19/H-21 desde la Fase 2 **no los ejecutaba
nadie**: `ci.yml` no tenía un solo paso de `cargo` y `check.ps1` tampoco. Nueve
tests escritos como gate y corridos por ninguna puerta durante 26 días — la
variante más silenciosa de H-22, porque aquí ni siquiera había una salida que
alguien pudiera malinterpretar. Añadidos el job `desktop-shell` a la CI y el paso
`[1b/4]` a `check.ps1`. (Fases 3, 15 y 27 encontraron lo mismo en otras puertas.)

**GATE PASADO.** `scripts/f28_gate_updater.ps1` — **13 comprobaciones + 1
medición, exit 0**: el endpoint es nuestro, https y termina en `latest.json`; la
sonda de red mide el estado real de hoy (**HTTP 404 ⇒ `UPDATE_SIN_PUBLICAR`**,
que es la verdad); los **19** tests del shell (9 heredados + 10 de esta fase); y
el generador de manifiestos real contra el contrato del plugin, **con tres
controles negativos** (sin `windows-x86_64`, versión que no es semver completo, y
firma vacía).

**Verificado por mutación (la pregunta 4). 12/12** sobre los tres artefactos que
deciden: reponer el endpoint del tercero, pasarlo a `http`, volver a colapsar el
404 en falta de red, borrar la rama de transporte, hacer que la mala
configuración se disfrace de red, volver a culpar a internet cuando el servidor
sí contestó, dejar un desenlace sin acción, dar el mismo código a dos
desenlaces, prometer que se instala solo, quitar el tope de tiempo, y dos sobre
el validador del manifiesto. Todas **rojas**, restauración verificada por hash.

**Y el gate se cazó TRES agujeros a sí mismo, que es el motivo de tenerlo.**
En la primera pasada escapaban **2 de 12**, y la corrección destapó la tercera:

1. y 2. **Los dos guards que leen la FUENTE con `include_str!` se satisfacían
   con el literal de su propia aserción.** Buscaban `"E::Reqwest(_) | …"` y
   `".timeout(UPDATE_CHECK_TIMEOUT)"` en el fichero **entero** — y esos textos
   aparecen también dentro del `assert!`, así que **borrar el código real los
   dejaba VERDES**. Es la patología que ya destapó la Fase 14 («mi propio guard
   era inerte»). Arreglado recortando la fuente al trozo anterior a
   `#[cfg(test)]`. Con eso las dos mutaciones pasan a rojo.
3. **Los controles negativos del generador aceptaban un *traceback* como
   rechazo.** Exigían sólo `exit != 0`, y al anular la comprobación de
   plataforma el validador seguía saliendo distinto de cero… con un `KeyError`.
   Peor: al endurecerlos salió que **los tres llevaban pasando por un traceback
   desde el principio**, porque `Set-Content -Encoding utf8` de PowerShell 5.1
   escribe **BOM** y `json.loads` reventaba en la primera columna. Es decir: los
   controles negativos **nunca habían ejercitado la validación**. Ahora se exige
   el **diagnóstico** y la ausencia de traceback, el gate escribe sin BOM y el
   generador lee con `utf-8-sig`. Mismo escape que se cazó en la Fase 27.

**Lo que el gate NO observa, y por qué.** No pilota la ventana recorriendo los
cinco desenlaces. `Updater::check()` exige un `AppHandle`, y construirlo en un
test obliga a activar la feature `test` del crate `tauri` — una dependencia que
la regla del proyecto no permite tomar sin permiso. Lo no cubierto es el tramo
«el crate devuelve X» → «nuestra función recibe X»; está medido **por lectura**
(`updater.rs:483-530`, citado dentro de `outcome_of_error`) y la comprobación
manual equivalente está escrita en `docs/04` §6.1. Se dice en vez de disimularlo.

**Dos detalles del crate que decidieron el diseño del manifiesto.** (1) La clave
de plataforma tiene que ser **`windows-x86_64` a secas**: `get_urls` sólo prueba
la variante `-nsis` cuando el binario lleva marcador de bundle, y el `app.exe` de
`cargo` no lo lleva (medido: `__TAURI_BUNDLE_TYPE_VAR_UNK`), así que un manifiesto
sólo con `-nsis` funcionaría en el instalador y fallaría en desarrollo. (2)
`get_urls` corre **ANTES** de comparar versiones, así que un manifiesto sin
nuestra plataforma no da «ya estás al día» sino `TargetsNotFound`.

**Riesgo abierto — NUEVO-13.** El repositorio es **privado**. Mientras lo sea, el
updater dará 404 a todos los usuarios aunque el workflow publique correctamente.
Las salidas son hacer público el repo, crear un repo público sólo de releases, o
alojar el manifiesto en un servidor propio. **Ninguna es técnica: es una decisión
de negocio** y no se toma sin el usuario. `release.yml` lo dice en su cabecera.

**Riesgo abierto — NUEVO-14.** Deriva de versión: hay tags **locales** `v0.2.0` y
`v0.4.0`, `tauri.conf.json` declara `0.2.0`, y el remoto no tiene **ningún** tag.
El workflow aborta si el tag y la config no coinciden, pero la deriva es de hoy.

**Lo que NO se hizo, y por qué.** (1) No se cableó `download_and_install`: sigue
sin haber ningún release contra el que probarlo, y prometer un camino que no se
puede ejercitar es exactamente lo que H-20 denunció. El texto de
`UPDATE_DISPONIBLE` dice explícitamente que la instalación es manual, y hay un
test que lo exige. (2) No se re-añadió `updater:default` a la capability: desde
la Fase 2 lo conduce Rust, y la superficie desde el webview sobra. (3) No se
corrió el workflow de release: exige secretos que sólo puede crear el usuario.

---

### FASE 29 (CERRADA) — Terminar la revisión que el límite de sesión cortó · **M** · 🟡 P2 · *auditoría*

**Por qué va al final.** Ninguna fase anterior depende de ello. Pero hasta
cerrarla, la respuesta a «¿está todo listo?» tiene un margen sin cuantificar.

**Trabajo.**
1. Los gates de las **14 fases, uno a uno**, con la pregunta 4: *¿falla el gate
   si se rompe lo que dice defender?* Esta patología ya apareció **dos veces** en
   este repositorio (Fase 3: un gate de física que pasaba con el bug dentro;
   Fase 6: un guard que se anulaba a sí mismo).
   **Añadir un patrón concreto a buscar, aportado por las Fases 14 y 28: el
   guard que lee la FUENTE y se satisface con el literal de su propia
   aserción.** En la Fase 28 escapaban así **dos de doce** mutaciones hasta que
   se recortó la fuente al trozo anterior a `#[cfg(test)]`. Cualquier guard que
   use `include_str!`, AST o `grep` sobre su propio fichero es sospechoso.
   **Y antes que nada, comprobar que la puerta CORRE:** los 9 tests de Rust del
   shell no los ejecutaba ni la CI ni `check.ps1` (Fase 28).
2. Correr la suite completa **con `py -3.14`** y publicar números reales:
   cuántos pasan, cuántos se saltan, y qué defiende lo que se salta.
3. Los dos hallazgos numéricos nunca medidos: el **operador de suavidad de 4º
   orden** (ACAD-3) y la **frontera de Dirichlet que nadie eligió** (ACAD-4).
4. Estructura y complejidad hoy (H-3, H-9, H-16, H-35); seguridad y red (H-15,
   H-21); listas de tolerancia que hayan crecido.
5. **Re-escribir la tabla §1.3 de `docs/06`** con el estado real.

**Gate.** Cada fila de §1.3 con fecha de re-medición y `ruta:línea`. Una fila sin
evidencia no cuenta como verificada.


### ✅ EJECUTADA — 2026-09-06

**Lo primero que midió esta fase fue a sí misma, y salió mal.** Se lanzaron **14
verificadores en paralelo**, uno por fase, para levantar la anatomía de cada gate.
**Los 14 murieron por límite de sesión** (`You've hit your session limit`), 1,15 M de
tokens gastados y **cero** resultados aprovechables. Es exactamente lo que originó esta
fase —«terminar la revisión que el límite de sesión cortó»— y ya había pasado dos veces
en este repositorio: 26 de 32 agentes en la auditoría del 04-ago, 21 de 24 en la
revisión de cierre del 23-ago. **Tres de tres.** El trabajo de abajo está hecho a mano,
secuencial, que es como se cerraron las catorce fases anteriores. La lección, que
conviene escribir para no volver a pagarla: *en este repositorio la delegación masiva no
es una optimización, es un modo de fallo conocido.*

---

#### 1. ¿Corre la puerta? — **152 pruebas escritas como gate que no ejecuta nadie**

La Fase 28 pidió preguntar esto **antes** que la 4ª pregunta del gate. La respuesta es
peor que la suya (9 tests de Rust), y está en `docs/06` §1.4.1 con su tabla. En corto:
**56** tests bajo `scripts/validation/` (que `pytest.ini:2` declara en `testpaths` y por
los que **ningún** paso de CI ni de `check.ps1` pasa), **57** recorridos de Playwright
(`ci.yml` no menciona `playwright` en ningún job) y **39** tests marcados `slow` sin
paso propio. Entre ellos, los gates de aceptación de las **Fases 11 y 14 al completo**
(11 y 2 tests) y la mitad de recorrido de usuario de las Fases **1, 9, 10 y 13**.

Hay un guard que existe justo para esto —`tests/test_fase3_ci_guards.py:214`— y **no lo
ve**: sólo mira el marcador `validation`, y sólo dentro de `tests/`. Hace lo que dice;
lo que dice es más estrecho que el problema.

**Dos puertas más que no corren, y una que sí.**
· `scripts/validation/f14_implicit_geology_experiment.py:333` —el instrumento que MIDE
el criterio de aceptación de la Fase 14— **muere con `KeyError: 'CONTROL_geologia_falsa'`**:
pide una clave que no existe (los brazos se llaman `CONTROL_falsa_suavidad` y
`CONTROL_falsa_smallness`, `:264-265`). Medido corriéndolo con `--seeds 1`: hace **las
nueve inversiones**, imprime la tabla pareada entera y revienta en la sección
«VEREDICTO», **antes de escribir su JSON**. Hoy la medición de la Fase 14 no se puede
reproducir.
· `check.ps1` no puede pasar en la máquina de desarrollo: invoca `python`, que aquí es
**3.11.9 sin numpy y sin pytest**. Es `NUEVO-12`, ya anotado por la Fase 27 — pero la
ficha se quedaba corta: no es sólo que `deps_closure.py` dé falsa alarma, es que el paso
`-Tests` **no puede ni arrancar** (`No module named pytest`).
· La puerta de la Fase 2 **sí corre y está verde**: `cargo test --lib` → **19 tests,
19 ok**, 2 min 21 s. Era el arreglo de la Fase 28 y aguanta.

---

#### 2. ¿Defiende la puerta? — **15 de 16 mutaciones cazadas**, y la que escapó es el hallazgo

Arnés: `mutar.py` (en el scratchpad de la sesión, no se commitea). Para cada mutación:
snapshot del fichero → línea base **verde exigida** → sustitución exacta y única →
corrida del gate → restauración → **verificación SHA-256 byte a byte**, con aborto
ruidoso si la restauración no es idéntica. Esa última comprobación no es paranoia: este
repositorio vive en OneDrive y ya tiene documentada una reversión a media corrida
(Fase 22). Las 16 restauraciones salieron byte-idénticas.

La tabla completa está en `docs/06` §1.4.3. **La que escapó**: duplicar 155 líneas de
`gravimetry.py` dentro de `magnetometry.py` **no puso rojo** el gate de la Fase 7. No es
un fallo del arnés: `study_duplication.py:158-175` cuenta **huellas distintas**
compartidas entre dos ficheros, no ocurrencias, y el bloque que copié **ya estaba
compartido**. Repetida con un bloque no compartido, el gate se puso rojo. Es decir:
**el criterio «< 40 ventanas» defiende contra duplicación nueva, no contra que la
existente se multiplique.** Y el gate vigila **un** par: los tres peores de hoy son
otros —`gravimetry↔geophysics_service` **72**, `gravity_import_api↔gravimetry` **67**,
`gravity_import_api↔geophysics_service` **64**— y la duplicación de
`api/gravity_import_api.py` **consigo mismo** (**102** ventanas) no la mira nadie: el
baseline la guarda **vacía** (`"propio": {}`).

**El patrón que la Fase 28 pidió buscar —el guard que se satisface con el literal de su
propia aserción— no aparece confirmado en ninguno de los 29 ficheros de `tests/` que
leen código fuente.** Los dos que más se acercan ya se defienden a propósito y lo
explican con la medición (`test_fase6_limpieza_verificada.py:52` y `:417-431`). Sí hay
**un agujero latente y hoy vacío**: `test_fase9_camino_de_usuario.py:36` mete `"e2e"` en
`_WEB_SCAN_DIRS`, de modo que una ruta cuyo único consumidor sea un recorrido de
Playwright contaría como «tiene camino de usuario» —y esos recorridos no los ejecuta
nadie—. Medido: de las **64** rutas del backend, **0** dependen hoy de eso. Arreglo de
coste cero: sacar `"e2e"` de la tupla, o volver a correr los recorridos.

---

#### 3. La suite completa con `py -3.14`: los números, y el que impide dar uno

**Lo colectado, que ya es un hallazgo.** `pytest` con los `testpaths` que declara
`pytest.ini:2` colecta **2.912** pruebas: **2.856** en `tests/` y **56** en
`scripts/validation/`. La selección del job de PR (`pytest tests/ -m "not slow"`) toma
**2.801** y deselecciona **55**. O sea: entre lo que el `pytest.ini` declara y lo que la
CI ejecuta hay **111** pruebas de diferencia, y de ellas 95 no las recoge ningún otro
paso (§1.4.1 de `docs/06`).

**Lo que la suite completa NO permite decir, y por qué.** No se puede publicar «pasan N,
se saltan M» de la suite entera, porque **la suite entera no termina**: se lanzó y a la
1 h 45 min seguía dentro de **un solo test**, `tests/test_doi_calibration.py::test_doi_within_physical_range`,
al **9 %** de progreso. Lanzado en solitario y con `--log-cli-level=INFO` para ver dónde
estaba, a los 45 min seguía en su **primera** inversión. El log dice por qué: el caso
declara un núcleo de 10×8×10 (800 celdas) que **con el padding de producción** se
convierte en `20×18×20 = 7.200`, de las que 5.142 entran al solver, y despacha a
**TRF/bounded** sobre un sistema de 10.365×5.142 — tres veces, porque
`compute_uncertainty=True` obliga al par de inversiones del índice DOI.
**Ese test no lleva marca `slow`**, así que está dentro de la selección del job de PR,
cuyo comentario en `ci.yml` afirma que el paso «cuesta del orden de la hora» para 2.256
tests. Un solo test puede costar más que eso. Es `NUEVO-20`.

**Lo que sí se midió — la corrida completa, con su número.** Deseleccionando **ese** test
—y diciéndolo, que es la diferencia entre una medición y un truco— se corrió la selección
equivalente a la del job de PR con `py -3.14`. Colecta **2.856**, desselecciona **56** (los
55 `slow` más ése) y selecciona **2.800**. Resultado:

> **2.796 pasados · 5 saltados · 0 fallos · 0 errores · 8.158 s = 2 h 15 min 58 s.**

**Y el reparto de ese tiempo es el hallazgo, no el total.** Con `--durations=20`:
**20 tests de 2.796 (el 0,7 %) consumen 5.646 s, el 69 % de la corrida**, y **ninguno de
los veinte lleva marca `slow`**. Los cinco peores:

| test | s |
|---|---:|
| `test_fase3_joint_coupling.py::test_joint_padding_with_pgi_coupling` | **636,9** |
| `test_fase8_3_wiring.py::test_uses_posterior_std_when_available` | **509,9** |
| `test_project_run_flow.py::test_block_model_response_con_project_run` | **473,7** |
| `test_project_run_flow.py::test_geophysics_flow_crea_archivos` | **434,3** |
| `test_fase3_joint_coupling.py::test_joint_padding_runs_and_reduces_to_core` | **399,4** |

Es decir: el paso «Suite de tests», cuyo comentario en `ci.yml` declara «del orden de la
hora», **aquí cuesta 2 h 16 min y dos tercios de eso son veinte tests que ninguna marca
separa**. En un runner de GitHub puede ir más rápido; lo que se afirma es lo medido aquí.
El hallazgo no es la lentitud: es que **el marcador `slow` dejó de separar lo caro de lo
barato**. El propio comentario de `ci.yml` ya lo sospechaba en agosto —«la marca `slow`
dejó de separar nada hace tiempo»— y hoy tiene nombres propios y segundos.

**Qué defiende lo que se salta — y la corrección que hay que hacerle a la pregunta.** Los
saltos son **cinco, y ninguno es la física**:

| skip | motivo declarado | qué defendería |
|---|---|---|
| `test_simpeg_comparison.py:27` | SimPEG no instalado | contraste del motor contra una implementación de referencia |
| `test_field_data_complete_flow.py:325` | `discretize`/SimPEG no instalado | el mismo contraste sobre dato de campo |
| `test_field_data_complete_flow.py:372` (×2) | exige `TQ_RUN_LARGE_FLOW=1` | el flujo completo en configuraciones medianas y grandes |
| `test_f8_perf_budgets.py:83` | requiere navegador (Playwright) | presupuesto de render de 100k celdas a >30 fps |

Los cuatro primeros dependen de una dependencia opcional o de una perilla; el quinto
depende de **la puerta de Playwright, que §1.4.1 declara muerta**. Ninguno defiende física
de producción.

**Y aquí está la corrección.** La pregunta del plan —«qué defiende lo que se salta»— supone
que lo excluido aparece como *skip*. **No aparece.** La regresión física F9 no está entre
esos cinco: sus 8 tests `validation` llevan **también** `slow`, así que `-m "not slow"` los
**deselecciona antes** de que el `skip` de `tests/conftest.py:11-21` llegue a actuar. Los
cubre el nocturno y el gate `f9_gate_regression.py`, así que la exclusión es legítima —
pero **es invisible**. Y lo mismo vale, sin cobertura ninguna, para los 39 `slow` huérfanos
del §1.4.1. Ésa es la diferencia que importa: **un skip se cuenta, se imprime y se puede
auditar; una deselección no aparece en ningún informe.** Esta corrida informa «5 saltados»
y la verdad es que hay **56 deseleccionados**, de los cuales 39 no los ejecuta nadie en
ninguna parte.

---

#### 3. ACAD-3 y ACAD-4: los dos hallazgos numéricos que el expediente declaró «nunca medidos»

`docs/academic/00_INDICE.md` los lista con esa etiqueta literal, y
`docs/academic/01_matematica.md` §9 escribe, para el primero: *«No se ha medido nunca la
diferencia de resultado entre penalizar ‖Lm‖² y ‖∇m‖² sobre el mismo dato. **No existe
ese experimento**»*. Ahora existe:
`scripts/validation/f29_operador_suavidad.py` (declarado **diagnóstico** en `GATES.json`,
no puerta: su respuesta puede ser legítimamente «no cambia nada» — y para ACAD-3 lo es).

**El diseño, y por qué es un 2×2 y no dos experimentos.** Las dos preguntas son
ortogonales, así que se cruzan: *orden* {4 = ‖L m‖², el de producción · 1 = ‖B m‖², el de
Li & Oldenburg} × *frontera* {Dirichlet, la que emerge del recorte · Neumann, la diagonal
recalculada}. Los cuatro operadores se derivan de **la misma `L_active` que arma el
motor**, con álgebra exacta —`cortadas_i = −Σ_j L_active[i,j]` es el peso de las aristas
hacia celdas muertas, y `B_dirichlet ᵀ B_dirichlet = −L_active` exactamente—, de modo que
comparten kernel, σ, pesos, bounds y solver: lo único que cambia es el operador. Mundo: el
dique inclinado a 60° de `tests/test_benchmark_dipping_dike.py`, anti-inverse-crime ×3
(discrepancia fina-vs-gruesa **4,08 %** del pico frente a 2 % de ruido), semillas pareadas,
`alpha_spatial = 1.0` (**el punto de producción**).

**El control, que es lo que hace honesta la medición.** Si no hay celdas inactivas,
`L_active == L_full`, sus filas suman cero y Dirichlet **es** Neumann. El experimento lo
exige: en el mundo plano (2.016 celdas, `n_dead=0`, `max|Σfila| = 0.0`) los dos brazos
salen **idénticos en las 5 métricas y en las 3 semillas, Δ = 0,000e+00 exacto**. Un arnés
que «encontrara» diferencia ahí estaría midiendo ruido del solver.

**ACAD-4 — la frontera de Dirichlet que nadie eligió: EL SESGO ES REAL, Y NO CUESTA
TARGETING.** Mundo con topografía: 1.936 celdas activas, **48 en la frontera cortada**
(2,5 %), `max|Σfila| = 1.0` (las filas dejan de sumar cero, como el expediente describe).
Pareado, Dirichlet (producción) vs Neumann:

| métrica | Dirichlet (hoy) | Neumann | Δ | semillas |
|---|---:|---:|---:|---|
| `abs_media_primera_banda` (amplitud media en la primera capa activa) | 0,0812 | **0,0838** | **+2,7 %** | Neumann mayor **3/3** |
| `nitidez_contacto` | 0,0442 | **0,0444** | +3,2 % | Neumann mayor **3/3** |
| `pearson_r` | **0,1729** | 0,1622 | −4,3 % | **Dirichlet mayor 3/3** |
| `pr_auc` | 0,1629 | 0,1633 | +0,2 % | Neumann mayor 2/3 |
| `iou@vol` | 0,1186 | 0,1186 | 0 | idénticas 2/3 |

Leído en una frase: **la condición implícita SÍ aplana el modelo justo bajo la topografía,
que es exactamente lo que el expediente temía, y el número es −2,7 % de amplitud en la
banda superficial, consistente en 3 de 3 semillas. Pero no empeora la recuperación**: el
PR-AUC es indistinguible y la correlación con la verdad es **mejor** con Dirichlet (3/3).
O sea: es un sesgo medible con signo predicho, y en este mundo su precio es cero.

**ACAD-3 — el operador de cuarto orden: NO se sostiene que sobre-suavice.** Pareado,
orden 4 (producción) vs orden 1 (Li & Oldenburg), misma frontera:

| métrica | mundo plano | mundo con topografía |
|---|---|---|
| `pr_auc` | orden 1 gana **2/3** (+2,1 %) | orden 1 gana **1/3** (orden 4 mejor) |
| `iou@vol` | idéntico | orden 1 gana **2/3** |
| `pearson_r` | orden 1 gana **1/3** | orden 1 gana **1/3** |
| `nitidez_contacto` | orden 1 gana **0/3** ← el de **cuarto** orden es más nítido | orden 1 gana **3/3** |

**Ningún criterio favorece al primer orden en los dos mundos, y el que la hipótesis
señalaba —la nitidez del contacto— cambia de signo entre ellos: 0/3 en el plano, 3/3 con
topografía.** La preocupación del expediente («penalizar la curvatura al cuadrado
sobre-suaviza de forma perjudicial para localizar cuerpos compactos») **no se sostiene en
el mundo plano**, donde el operador bi-armónico produce contactos *más* nítidos en las
tres semillas. La respuesta a la Pregunta 1 del expediente es, por tanto, la útil de las
dos que él mismo enumeraba: **no hay que gastar esfuerzo ahí.**

**Límites de esta medición, dichos antes de que los pregunten.**
(a) **3 semillas**, y en este repositorio está medido que el motor es **bimodal** frente al
ruido (1 de cada 3 realizaciones se desvía 170 m con diagnósticos idénticos): tres
semillas eligen una dirección, no fijan una cifra.
(b) **Un solo α**, el de producción. El diseño pedía barrer λ por brazo —porque los cuatro
operadores tienen normas distintas y a α fijo se compara la FUERZA del regularizador, no
su FORMA—, y el barrido **no se corrió**: cada inversión cuesta ~65 s y el barrido
completo son horas. Lo que aquí se responde es *«qué obtiene hoy el usuario»*, no *«cuál
es el techo de cada operador»*. Se dice en vez de disimularlo.
(c) **Una geometría** (dique a 60°) con dos topografías.
(d) `media_primera_banda_sobre_dique` sale **NaN por construcción** en este mundo: el techo
del dique está a 100 m y la primera capa activa a 15 m, así que ninguna celda de esa banda
es dique. Se reporta NaN en vez de un cero que parecería un resultado.

**Y un defecto del propio arnés, cazado antes de publicar.** La primera corrida midió
sobre el vector completo, y **el motor devuelve `NaN` en las celdas de aire**: `np.sort`
manda los NaN al final y corre el umbral de volumen, y `corrcoef` devuelve NaN entero — el
mundo con topografía salía con `pearson_r = nan` y un IoU de 0,0636 que no significaba
nada. Las métricas se recalcularon **sólo sobre el dominio activo**. Es el error que este
repositorio tiene documentado cinco veces (medir una configuración y hablar de otra), esta
vez detenido en el borde.

**Un dato de propina que cambia el alcance de ACAD-4 y que no estaba escrito en ninguna
parte.** El expediente presenta la frontera implícita como algo que aparece «con
topografía o con poda». **Aparece siempre**: el padding de producción es incondicional
(H-38) y **crea celdas de aire por encima de la superficie**. Medido sobre una corrida
real de `run_geophysics_inversion` (`tests/test_doi_calibration.py`, núcleo 10×8×10 →
malla con padding 20×18×20): **2.000 de 7.200 celdas (27,8 %) son aire** y 58 más mueren
por sensibilidad. Es decir, la condición de Dirichlet que nadie eligió **está activa en
todas las corridas del producto**, no sólo en las que declaran topografía — con un 27,8 %
de frontera en vez del 2,5 % de este experimento.

---

#### 5. Estructura, complejidad, seguridad y listas de tolerancia (re-medidas)

Todo con fecha y `ruta:línea` en la tabla §1.3 de `docs/06`. Los titulares:

| Hallazgo | 2026-08-04 | 2026-09-06 |
|---|---|---|
| **H-3** estructura | 21 funciones = 26,4 % del código; `run_geophysics_inversion` 1.996 LOC / CC 201 | Esa función se partió, **pero el criterio de la Fase 8 no se cumple**: **8** funciones > 300 LOC, CC máx **181**, firma máx **39** args. Las 21 más largas = **13,7 %** de 56.714 LOC (122 ficheros, 1.121 funciones) |
| **H-9** duplicación | 228 ventanas entre los dos motores | **20** (criterio < 40) — y el gate es ciego a los tres peores pares de hoy |
| **H-15** escucha | `0.0.0.0` por defecto | **`127.0.0.1`** + aviso ruidoso si se expone sin auth (`core/config.py:152`, `main.py:126-134`) |
| **H-16** frontend | 8 ficheros = 40,2 % de 28.327 LOC; `PrepPanel` con 41 `useState` | **34,1 %** de **37.366** LOC (creció 32 %); `useState` máximo **10**, bajo el techo de 12 |
| **H-21** red | 3 llamadas directas navegador→backend | **0** (guard verde hoy) |
| **H-35** capas | 41 % de `core/` es dominio | **0** — los tres ficheros viven en `services/`; `core/` = 11 ficheros, 1.881 LOC |

**Listas de tolerancia** (ninguna ha crecido sin motivo escrito; se publican para que se
pueda vigilar): `HUERFANOS_TOLERADOS` **4** · `SIMBOLOS_BORRADOS` **19** ·
`CUBIERTOS_POR_EL_GATE_F9` **1** · `RUTAS_SIN_UI_TOLERADAS` **9** ·
`PROXIES_SIN_LLAMADOR_TOLERADOS` **1** · `INYECCION_TOLERADA` **3** ·
`CONTRATOS_AUN_A_MANO` **4** · `PERILLAS_ENTERRADAS` **5** ·
`SOLO_SITIO_PERMITIDO` **1**.

**Y un baseline que hay que mirar con la lista de tolerancia puesta:**
`scripts/ci/ast_baseline.json` no vigila el criterio de la Fase 8 —vigila
NO-REGRESIÓN—, así que **codifica como suelo aceptado** una CC de 181 y una firma de 39
argumentos. Un gate que no puede empeorar tampoco obliga a mejorar; conviene decirlo en
vez de leer su verde como «criterio cumplido». Y `duplication_baseline.json` va
**desactualizado en tamaño** (115 ficheros / 18.518 ventanas frente a 121 / 20.718 de
hoy) aunque el número que decide, el par de la Fase 7, sigue en 20.

---

#### 6. La tabla §1.3, re-escrita

`docs/06_AUDITORIA_TECNICA_INTEGRAL.md` §1.3 se re-escribió entera: **39 filas** con **estado de hoy, fecha y `ruta:línea`**, y con el título corregido —decía «Los 8 hallazgos que importan» sobre una tabla de 39—. Recuento medido sobre las **41 filas** (39 hallazgos + 2 autocorrecciones): **26 ✅ CERRADO** · **8 🟡 PARCIAL** (mitigados, con el resto medido) · **5 🔴 VIVO** — H-3 (estructura), H-24 (traceback en el ZIP), H-30 (roca país fija en el frontend), H-38 (padding incondicional) y H-39 (MVI y tensor siempre dipolo) — · **2 ⬜ NO RE-MEDIDO** — H-26 (las cuatro formulaciones de regularización, sin fase dueña) y H-32 (su sitio original ya no existe; lo que hay hoy en `Scene3D.tsx` es otra cosa) —, declarados como tales en vez de heredar su estado anterior. Se añadió una sección nueva, **§1.4**, con el censo de puertas, la tabla de mutaciones y el rastreo del patrón de auto-satisfacción.

**El gate de esta fase, medido sobre su propio entregable.** «Cada fila con fecha de re-medición y `ruta:línea`; una fila sin evidencia no cuenta como verificada.» De las 41: **36 con `ruta:línea`**, **3 cuya evidencia es una AUSENCIA** (H-6, H-7, H-31 — un fichero borrado no tiene línea; se declara así, y se dice además que ningún guard la sostiene) y **2 autocorrecciones del auditor**, cuya evidencia legítima es la sección de `docs/06` donde se argumentan. **0 filas heredadas** sin volver a mirarlas.

---

#### Lo que esta fase NO hizo, y por qué

1. **No se corrieron los recorridos de Playwright.** Exigen `next build` + `next start` +
   el backend en :8010 y un navegador instalado; es la puerta que §1.4.1 declara muerta,
   y resucitarla es trabajo de una fase con dueño, no de una auditoría. Lo que sí se
   hizo es **medir** que no corren y cuántas pruebas son.
2. **No se tocó ningún gate para arreglarlo.** Los cinco agujeros que esta fase mide
   —el `"e2e"` de `_WEB_SCAN_DIRS`, el marcador `slow` sin vigilante, `scripts/validation/`
   fuera de toda puerta, el `KeyError` de la F14 y el conteo por huellas únicas de la
   duplicación— quedan **anotados con su coordenada**, no parcheados. Una auditoría que
   arregla lo que mide deja de poder decir qué encontró.
3. **La historia de git de H-7 no se re-midió.** El árbol está limpio; purgar la historia
   reescribe 189+ commits y es una decisión del usuario, no de una auditoría.
4. **H-26 (cuatro funcionales de regularización) queda ⬜ NO RE-MEDIDO** y se dice: sigue
   sin fase dueña.

---

### FASE 30 — Subir el techo a `HIGH` · **M** · 🟡 P2 · *backend* · ✅ **CERRADA 2026-09-06**

**Lo que la ficha pedía, y por qué era decorativo.** La ficha decía: «lo que la Fase 30 tiene
que quitar es una sola entrada: `high_hold_pending_fase30` en `build_reconciled_verdict`».
Se midió eso **antes de tocar nada**, sobre las 75 corridas de confirmación de la Fase 26:

| pregunta | respuesta medida |
|---|---|
| corridas cuyo **único** limitante es `high_hold_pending_fase30` | **0 de 75** |
| corridas MEDIUM también capadas por `priority_class` | **44 de 44** |
| ⇒ **veredictos que cambia quitar sólo el hold** | **0 de 75** |

Ejecutar la ficha al pie de la letra habría dado el gate en verde —«0 corridas
SOBRECONFIADAS»— con **0 corridas en `HIGH`**: un 0 que mide un techo, no honestidad. Es la
**quinta** vez en este plan que el trabajo que pedía la ficha no era el defecto.

**El techo eran TRES, y el declarado no era el que mandaba.**

1. `high_hold_pending_fase30` — la retención honesta de la Fase 26. Inerte, como se ve arriba.
2. **`priority_class`** — capaba a MEDIUM **las 44 de 44** corridas MEDIUM, sin distinguir
   entre ellas: incluidas las de PR-AUC 1,000 y 11 m de error horizontal.
3. **`favorability.score ≥ 65`**, el requisito de `priority_class` para llegar a HIGH. En la
   MEJOR corrida del barrido (`depth_250m`, PR-AUC 1,000, error 11,3 m, con
   `technicalSummary.overall_level = GOOD` y `uncertainty_score = 0,0`) el score sale **44,9
   con los dos multiplicadores de calidad en 1,00**. El techo estaba en la aritmética de los
   factores, y uno de ellos —`anomaly_intensity`, peso 0,25— está **invertido**: da 0,000 a
   esa corrida y 1,000 a `worst_ldm_like` (PR-AUC 0,002, error 1.186 m).

**Trabajo hecho.** Se retira la retención; `priority_class` **deja de topear** y pasa a
publicarse con su papel y con el nivel que habría aportado (motivo semántico: mide atractivo
de *targeting*, no confiabilidad, y ya venía multiplicado por la calidad ⇒ la contaba dos
veces); y `HIGH` **deja de concederse por ausencia de defectos**: lo sella `_high_seal` con dos
pruebas medidas — resolución por debajo del peldaño más grueso del examen, y
`floor_mass_excess ≤ 0,5` (el número que el plan mandó traer, usado para **negar** el nivel
superior y no para degradar a LOW, que es donde dejaba sólo 12 % de margen).

Que retirar `priority_class` es seguro está **medido**: las 3 corridas que serían
SOBRECONFIADAS si `HIGH` se soltara sin criterio (978,4 · 636,8 · 542,1 m) las cazan
`survey_confidence` y `model_reliability` por su cuenta. No era quien protegía de la
sobreconfianza: era quien impedía medirla.

**Gate — PASADO sobre 150 corridas** (semillas frescas 310007 + 1009·i), con los tres
criterios declarados antes de correr:

* **G1 honestidad:** cuadrante SOBRECONFIADO = **0**.
* **G2 alcanzabilidad:** `HIGH` en **36 de 150** = **24,0 %**. Sin este
  criterio el gate se cumple sin que el cambio haga nada.
* **G3 no regresión:** nada con `resolves_anywhere = False` ni con `is_floor_smear = True`
  supera LOW.

El peor `HIGH` de las 150 corridas se equivoca en **164,9 m**. **21**
corridas habrían salido `HIGH` sin el sello, **9** de ellas con error > 200 m.

**Mutación: 12 de 12 cazadas**, fichero restaurado con hash idéntico. Dos no son hipotéticas: **M11** es un defecto que esta fase **escribió y corrigió** (el techo afirmaba «el sello ya está superado» en corridas LOW donde el sello había fallado y no aparecía en `capped_by`), y **M7** es una rama del worst-of que llevaba desde la Fase 21 **sin ejecutarse nunca** —con el techo puesto el mínimo era siempre MEDIUM o menos— y que al abrirse publicaba «limitado por: …» en la corrida mejor calificada del sistema.

Registro: `validation/PREREGISTRO_2026-09-06_fase30.md` (escrito antes de medir) y
`validation/HALLAZGO_2026-09-06_techo_high.md`. Gate: `py -3.14 -m validation.exp_high_ceiling`.

**Lo que NO hace, declarado:** no arregla `favorability` (**NUEVO-15**: `anomaly_intensity`
invertido, `structural_gradient` y `msx_support` casi constantes; **NUEVO-16**: la Regla 3 de
`compute_priority_class_from_report` lee `quality_label`, una clave que
`compute_favorability_score` **no devuelve** — nunca se ha ejecutado). No toca el frontend
(NUEVO-10 sigue abierto). Re-invirtió además las dos corridas de **dato real** del
repositorio: LdM y San Nicolás salen **LOW las dos**, y ya salían LOW antes — las capa
`is_floor_smear` (Fase 26), no nada de esta fase. Lo revelador es que `survey_confidence` y
`model_reliability` dicen **HIGH** en ambas: sin el trabajo de la Fase 26 y con el techo
levantado, las dos habrían salido `HIGH`. Pero San Nicolás es un benchmark **aprobado** y
sale LOW (**NUEVO-17**, sin dueño). Y anota una **errata del barrido**: `baseline` y `depth_400m` son el
mismo mundo con distinto id, así que los «15 regímenes» son **14 casos distintos** — afecta al
conteo de la Fase 26, no a su ρ.

---


## 6. LO QUE **NO** HAY QUE HACER

Tan importante como el plan: dónde no gastar las semanas.

- **No re-litigar la profundidad.** La gravedad sola no la resuelve — es
  null-space, no bug, medido con **3.450 inversiones**. `depth_beta` es inerte y
  arreglarlo no mejora. Cerrado.
- **No implementar la sección económica.** NPV, LOM, pit y scheduling son
  **anti-scope permanente declarado** (H-8). Las tarjetas ya se borraron: que
  sigan borradas.
- **No desbloquear `HIGH` antes de que la señal discrimine.** ✅ **RESUELTO por la
  Fase 30 (06-sep), en el orden correcto.** Se conserva el razonamiento porque
  la regla que deja es permanente: *el nivel superior no se concede por ausencia
  de defectos, se sella con evidencia positiva*. Lo que sigue vigente:
  Hoy el checkerboard devuelve el mismo número siempre —por diseño, no por
  avería— y el worst-of lo usa de tope duro; eso **te está protegiendo**, porque
  1 de cada 3 corridas se desvía 170 m sin que ningún diagnóstico lo delate
  (ρ = 0,000). Liberar el techo antes produciría `HIGH` en corridas de 285 m de
  error. El orden es **Fase 26 primero, Fase 30 después**, y la 30 no se abre si
  la 26 no cerró con un número.
- **No invertir el default de `density_min`.** La recomendación está **RETIRADA
  por escrito** en `validation/HALLAZGO_2026-08-06_bound_por_defecto.md`: el
  PR-AUC 0,035 se midió con malla forzada, no con el flujo real, y al barrer
  regímenes **ningún brazo domina**. Es una variable de régimen. Lo accionable es
  hacerla **visible** (Fase 20), no elegirla por el usuario.
- **No citar números de una configuración hablando de otra.** Es el error que
  este proyecto tiene documentado **cinco veces** — la última, la auditoría delta
  del 26-ago citando el 0,035 retirado. Antes de usar un número de un hallazgo,
  lee su banner de corrección.
- **No «arreglar» ACAD-6** — no existe la contradicción que describe. Si se
  quiere tocar esa constante, el trabajo real es verificarla fuera de
  `n_active=256`.
- **No hacer refactors globales** para cerrar varios defectos de golpe. Las 20
  respuestas sin `exclude_unset` y las ~19 perillas huérfanas de `Scene3D` son
  deuda conocida y acotada; convertirlas en una fase «que lo arregla todo» es
  exactamente lo que el repositorio prohíbe.
- **No prometer porcentajes desde la Fase 14.** Fueron 150 inversiones, un mundo
  y una λ. Alcanza para elegir un default, no para una cifra en una propuesta
  comercial.

---

## 7. GOTCHAS DE ENTORNO

- **Usa `py -3.14`, no `python`.** El intérprete del PATH es 3.11.9 **sin
  numpy**; `py -3.14` tiene numpy 2.4.4 y coincide con `.python-version`.
- No hay `.venv` en el proyecto.
- Tauri sirve en el **primer puerto libre 3000..3011** ⇒ `localStorage` puede
  vaciarse solo entre arranques.

---

*Documento generado el 2026-08-23 re-midiendo `docs/06_AUDITORIA_TECNICA_INTEGRAL.md`
y `docs/academic/00_INDICE.md` contra el árbol de trabajo. Versión navegable:
https://claude.ai/code/artifact/10b591e1-08cf-4e5f-ba8b-a3d1acc30d1e*
