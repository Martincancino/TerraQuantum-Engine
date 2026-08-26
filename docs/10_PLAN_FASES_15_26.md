# TerraQuantum — PLAN DE FASES 15 a 26

> **Revisión de cierre del plan §10** · 2026-08-23 · rama `fases-19-25-cierre`
> Verificado contra el **árbol de trabajo**, no contra HEAD. Ninguna afirmación
> se apoya en documentación: todas citan `ruta:línea`.

---

## CÓMO USAR ESTE DOCUMENTO

En una sesión nueva de Claude Code, abierta en la raíz del proyecto:

```
Lee docs/10_PLAN_FASES_15_26.md y ejecuta la Fase 19 completa.
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

**NO verificado (queda como Fase 26):** los gates de las 14 fases uno a uno, la
ejecución real de la suite, estructura y complejidad hoy, el operador de
suavidad de 4º orden y la frontera de Dirichlet, seguridad y red, listas de
tolerancia, higiene del repositorio, código muerto nuevo en el frontend.

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
| **NUEVO-1** | La **inversión conjunta** ignora la topografía por completo y su reporte no tiene el canal de avisos que la Fase 1 sí cableó en las rutas gravimétrica y magnética | `services/joint_inversion.py` |
| **NUEVO-2** | Cambiar de pestaña pierde el **mapeo de columnas, los puntos Helmert, los sondajes y 25 parámetros** porque `PreparacionView` se desmonta. (Los archivos y el bbox sí sobreviven — la memoria decía «los 41 parámetros», y es menos que eso) | `componentes/views/PreparacionView.tsx` |
| **NUEVO-3** | El **CSV corregido** por el asistente de gravimetría se descarta al cambiar de pestaña, y el paquete se rearma sobre el **CSV crudo** | flujo PrepPanel → paquete |
| **H-36** | `resultIsStale` es una **lista a mano ya atrasada**: los parámetros de la Fase 14 no están, así que cambiarlos no marca el resultado como desactualizado. (La otra mitad, `modelRunKey`, sí es un invariante sólido) | `store/useAppStore.ts` |
| **ACAD-12** | `bulk_rock_mass_kg` **contiene toneladas** — factor 1.000. El propio comentario documenta el renombrado `tonnage → bulk_rock_mass_kg` como «compliance-safe»: el renombrado creó la mentira de unidad | `exploration/gravimetry.py:4233,4248` |
| **ACAD-13** | La exportación calcula el contraste contra el **literal 2.6** mientras el motor usa `base_density`, que es configurable | `export_service.py:31,210` vs `geophysics_service.py:394` |
| **H-20** | El updater apunta a `github.com/TerraQuantum/terraquantum`; el remoto real es `Martincancino/TerraQuantum-Engine`. No hay workflow de releases ni llamada a `download_and_install`. El fallo se le presenta al usuario como si fuera falta de internet | `src-tauri/tauri.conf.json:34`, `lib.rs:975` |
| **NUEVO-4** | El `.spec` **traga la excepción**: `_safe_submodules` devuelve `[]` ante cualquier fallo y `build_desktop.ps1` nunca instala ni verifica `requirements.txt` ⇒ el instalador puede salir sin OMF y sin avisar | `terraquantum_backend.spec:21-25,54-55` |
| **H-39** | Los kernels de **MVI y tensor siguen ignorando `near_field_mode='prism'`** y usan siempre dipolo. La auditoría lo marca `[HECHO]`: ahí significaba «leído», no «arreglado» | `exploration/magnetometry.py` |
| **H-34** | **Turbo sobrevive en la leyenda** de `MultiPhysicsControls`, describiendo colores que ya nadie pinta. Peor que antes: ahora la leyenda miente sobre lo que se ve | `componentes/.../MultiPhysicsControls.tsx:32,335` |
| **H-23** | Sin lockfile con hashes, y `build_desktop.ps1` nunca compara el intérprete con `.python-version`. (Lo bueno: **0 dependencias sin techo**, eran 7; PyInstaller pineado; `.python-version` declarado y consumido por la CI) | `requirements.txt`, `scripts/build_desktop.ps1` |
| **NUEVO-5** | `six`, transitiva de `omf`, quedó **sin pin** — el propio comentario nombra cuatro y pinea tres | `requirements.txt:111-113` |
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
- **H-27** — El aviso de topografía plana llega al usuario extremo a extremo…
  **salvo en la ruta conjunta** (ver NUEVO-1).
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

### FASE 15 — Poner a salvo tres fases que solo existen en tu disco · **S** · 🔴 **P0** · *git*

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

### FASE 16 — La ingesta deja de adivinar el rol de una columna · **S** · 🔴 **P0** · *backend* · H-F11-1

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

### FASE 17 — La corrección de terreno usa la componente vertical · **M** · 🔴 **P0** · *backend* · ACAD-0, ACAD-9

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

### FASE 18 — El experimento que cierra la rotación de 90° · **M** · 🔴 **P0** · *backend, medir* · ACAD-1

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

### FASE 19 — Una sola convención de ejes, con guardia · **M** · 🟠 P1 · *backend* · ACAD-1, ACAD-1c

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

---

### FASE 20 — La preparación deja de evaporarse · **M** · 🟠 P1 · *frontend* · NUEVO-2, NUEVO-3

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

---

### FASE 21 — La inversión conjunta recupera topografía y avisos · **M** · 🟠 P1 · *backend* · NUEVO-1

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

---

### FASE 22 — Las unidades de la exportación dejan de mentir · **S** · 🟠 P1 · *backend* · ACAD-12, ACAD-13

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

---

### FASE 23 — «Desactualizado» por tipos, no por lista · **S** · 🟠 P1 · *frontend* · H-36

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

---

### FASE 24 — El instalador falla en voz alta cuando falta una dependencia · **M** · 🟡 P2 · *empaque* · NUEVO-4, NUEVO-5, H-23

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

---

### FASE 25 — El updater: o apunta bien, o se retira · **M** · 🟡 P2 · *empaque* · H-20

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

---

### FASE 26 — Terminar la revisión que el límite de sesión cortó · **M** · 🟡 P2 · *auditoría*

**Por qué va al final.** Ninguna fase anterior depende de ello. Pero hasta
cerrarla, la respuesta a «¿está todo listo?» tiene un margen sin cuantificar.

**Trabajo.**
1. Los gates de las **14 fases, uno a uno**, con la pregunta 4: *¿falla el gate
   si se rompe lo que dice defender?* Esta patología ya apareció **dos veces** en
   este repositorio (Fase 3: un gate de física que pasaba con el bug dentro;
   Fase 6: un guard que se anulaba a sí mismo).
2. Correr la suite completa **con `py -3.14`** y publicar números reales:
   cuántos pasan, cuántos se saltan, y qué defiende lo que se salta.
3. Los dos hallazgos numéricos nunca medidos: el **operador de suavidad de 4º
   orden** (ACAD-3) y la **frontera de Dirichlet que nadie eligió** (ACAD-4).
4. Estructura y complejidad hoy (H-3, H-9, H-16, H-35); seguridad y red (H-15,
   H-21); listas de tolerancia que hayan crecido.
5. **Re-escribir la tabla §1.3 de `docs/06`** con el estado real.

**Gate.** Cada fila de §1.3 con fecha de re-medición y `ruta:línea`. Una fila sin
evidencia no cuenta como verificada.

---

## 6. LO QUE **NO** HAY QUE HACER

Tan importante como el plan: dónde no gastar las semanas.

- **No re-litigar la profundidad.** La gravedad sola no la resuelve — es
  null-space, no bug, medido con **3.450 inversiones**. `depth_beta` es inerte y
  arreglarlo no mejora. Cerrado.
- **No implementar la sección económica.** NPV, LOM, pit y scheduling son
  **anti-scope permanente declarado** (H-8). Las tarjetas ya se borraron: que
  sigan borradas.
- **No perseguir HIGH en el veredicto de confianza.** El checkerboard QA no
  depende del dato, así que falla siempre y el worst-of lo usa de tope duro. Es
  una propiedad del diseño, no un fallo.
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
