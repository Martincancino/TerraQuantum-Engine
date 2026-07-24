# TerraQuantum — Rigor físico, presupuesto de error y red-team pre-lanzamiento

| Campo | Valor |
|---|---|
| Fecha | 2026-07-23 |
| Estado | PROPUESTA — plan de trabajo para antes del gate de venta (F10) |
| Depende de | F9 ✅ (regresión física congelada) · conecta con F11 (reducir no-unicidad con restricciones) |
| Objetivo en una frase | *"Saber EXACTAMENTE cuánto nos equivocamos hoy, sacarle el máximo al dato del cliente, y romper el sistema nosotros antes de venderlo."* |

---

## PRINCIPIO RECTOR (no negociable)

1. **Medir contra verdad conocida. Nunca creerle al motor —ni a una IA— sin oráculo.** La rigurosidad no viene de que el algoritmo (o el copiloto) sea inteligente; viene de comparar cada número contra una verdad independiente (benchmark publicado, solución analítica, dato real con sondaje). *Hoy mismo (F9) una suposición de "romper W_z" resultó falsa: `depth_beta` era inerte. Lo cazó la MEDICIÓN, no el razonamiento.*
2. **La no-unicidad es una LEY, no un bug.** La gravedad-sola no resuelve profundidad (medido: z-error 2675 m en régimen malo). Ni TQ ni VOXI ni Leapfrog la eliminan. Nuestro trabajo es **cuantificarla y comunicarla**, no fingir que la resolvimos.
3. **Toda mejora se valida midiendo ANTES de venderla.** Recordatorio medido: el cross-gradient joint NO mejoró DO-27. "Más features" ≠ "mejor". Si no mejora medido, se documenta y no se promete.
4. **"Robusto" ya está definido (F0):** o resultado válido, o error claro en español; JAMÁS basura silenciosa con sello "GOOD". "Resolver todo lo que podría pasar" es imposible y creerlo es peligroso. La meta es **cero corrupción silenciosa**, no cero fallas.

---

# PARTE A — Presupuesto de error: *"¿cuánto nos equivocamos HOY?"*

**Objetivo:** una TABLA honesta y reproducible del error del motor por **métrica × régimen**, contra verdad conocida. Sin esto no se puede mejorar ni vender con honestidad: es el mapa de "dónde servimos y dónde no".

**El error es dependiente del RÉGIMEN.** No hay "un" error; hay un error por combinación. Los ejes que importan (medidos/conocidos):
- **Profundidad del cuerpo** (somero resuelve; profundo entra en null-space).
- **Contraste** (Δρ / Δκ fuerte vs débil).
- **SNR** del dato (ruido de gravímetro/magnetómetro).
- **Densidad y extensión de la cobertura** (regla medida: extensión ≥ 2× profundidad objetivo, espaciamiento ≤ ½ profundidad).
- **Restricciones disponibles** (sin nada / + ancla / + petrofísica / + geología).

## Trabajo

- **A1 — Definir las métricas de error** (lo que un cliente entiende):
  - *Targeting horizontal* (m): dónde perforar. **Nuestra fortaleza medida (50–200 m).**
  - *Profundidad* (m): techo y centroide. **Nuestro límite honesto.**
  - *Densidad/magnitud* (t/m³): informativa vs null-space.
  - *Forma/estructura* (IoU, correlación horizontal): ¿coincide el cuerpo?
  - *Honestidad del reporte*: ¿el sistema DICE lo que no resuelve? (métrica propia, la vende nadie más).
- **A2 — Banco de verdad** (anti-inverse-crime obligatorio: el dato NUNCA se genera con el operador de la inversión):
  - **Sintéticos con verdad analítica** (esfera / dique inclinado / dos cuerpos / checkerboard, que ya existen en `tests/`) **barridos** sobre los 5 ejes de arriba → cientos de combos con verdad exacta.
  - **Los 4 benchmarks externos** (DO-27 publicado, Raglan dato real, San Nicolás campo real, LdM Bouguer real) — ya en F9, aquí se extienden con las métricas completas.
- **A3 — Correr y producir el ERROR BUDGET**: matriz medida `métrica × régimen → error`, reproducible (semilla fija), con reporte HTML/tabla. Reutiliza la infraestructura de F9 (`f9_regression_lib`, `field_validation_harness`).
- **A4 — Mapa de la frontera**: traducir la matriz a una frase por régimen — *"con este survey, el targeting horizontal es confiable a ±X m hasta ~Y m de profundidad; más profundo es extrapolación honesta."* Cablear al reporte del producto (ya existe `observable_depth_max_m` y el horizonte DOI de B2).

**Gate A (medible):** existe la tabla de error reproducible; cada celda tiene su verdad y su régimen; el reporte del producto NO promete fuera de la frontera medida (un test lo verifica: si el modelo dice "HIGH" en zona null-space, falla).

## RESULTADOS MEDIDOS — Parte A (2026-07-23, primera pasada)

Herramientas: `scripts/validation/error_budget.py` (barrido, 15 regímenes, esfera analítica anti-inverse-crime, config validada λ=1e-3 IRLS compacto = la que dio DO-27 53.7 m) + `error_budget_html.py` (reporte). Artefactos: `error_budget_report.json` / `.html`. **Números medidos, sin ajustar.** Tres conclusiones honestas:

**1. HORIZONTAL (dónde perforar) = la FORTALEZA, y se degrada PREDECIBLE:**
| Régimen | Error horizontal |
|---|---|
| Somero 250 m, buena cobertura, señal clara | **2 m** |
| Baseline (400 m) | **14 m** |
| Profundo 600 m / 900 m | 92 m / 114 m |
| Cobertura densa / media / dispersa | 26 / 88 / 149 m |
| SNR alto / medio / bajo | 14 / 49 / 120 m |
| Contraste fuerte / débil | 14 / 87 m |
| Peor caso (profundo+disperso+ruidoso, tipo LdM) | **815 m** |

→ **Regla medida:** el targeting es perforable (≤ ~1–2 celdas) cuando la profundidad objetivo ≲ 1.5× el espaciamiento de estaciones y la señal es clara. Fuera de eso se degrada — y hay que decirlo. Esto ES el producto, y coincide con las validaciones externas (DO-27 53.7 m, Raglan 212 m).

**2. PROFUNDIDAD (cuán profundo) = NO se recupera:**
- El cuerpo recuperado se **ancla en la capa más somera (~62 m) en 13 de 15 casos**, dé igual que la verdad esté a 250, 400, 600 o 900 m. El error de profundidad = profundidad_real − 62 m (crece lineal: 187 / 337 / 537 / 837 m).
- No es "incierto": es **sistemáticamente somero**. Hipótesis fuerte (a probar en B): lo domina el hallazgo de F9 de que el **depth-weighting W_z es inerte** (la normalización de columnas Ws lo absorbe) → no hay nada empujando la masa a su profundidad.
- Matiz honesto: en el régimen REGIONAL de LdM (malla profunda) la masa hace lo OPUESTO (se hunde al piso). La DIRECCIÓN del sesgo depende del régimen; en ambos la profundidad está mal. Gravedad-sola NO resuelve profundidad = LEY, no bug.

**3. DENSIDAD (cuánta) = NO confiable:**
- 7–78 % del contraste real recuperado, sin patrón estable (compact IRLS sub-recupera magnitud + no-unicidad somero-débil ≡ profundo-fuerte). Sirve para "hay algo denso aquí", NO para "la densidad es X".

**Lo que abre para la Parte B (el hallazgo más valioso):** el sesgo somero parece dominado por el W_z inerte → **hipótesis #1 medible de B: si el W_z realmente actúa (no absorbido por Ws), ¿cuánto baja el error de profundidad?** Puede ser una mejora grande y barata (cambio de motor chico, alto impacto) — pero se MIDE antes de creerlo (regla de oro). Las otras palancas de B (Euler como prior de profundidad, ancla de sondaje) atacan lo mismo: fijar la profundidad con información independiente, porque la gravedad-sola no puede.

---

# PARTE B — Sacarle el MÁXIMO al dato (reducir el error con restricciones)

**Objetivo:** cada dato extra que el cliente entrega **recorta el espacio de modelos falsos-pero-consistentes**. Así lo hace la industria (UBC-GIF, SimPEG/PGI): no con "inversión más inteligente", sino con **información independiente**. Esto ES F11; aquí se ejecuta MEDIDO.

## Trabajo (ordenado por impacto / costo)

- **B1 — Cablear-y-MEDIR lo ya construido-sin-cablear** (costo: solo cableo; cada uno con su número de mejora):
  | Pieza | Qué recorta | Cómo se mide |
  |---|---|---|
  | Ancla dura + PGI/GMM (petrofísica de sondajes) | Fija densidad real donde hay pozo + estadística por unidad | error de densidad/profundidad con vs sin, en sintético con sondaje conocido |
  | **Euler / espectral como PRIOR de profundidad** (nuevo en F2B) | Profundidad INDEPENDIENTE de la inversión → fijar z0 del depth-weighting | z-error con vs sin el prior de Euler, en esfera/dipolo de profundidad conocida |
  | FTG (tensor gradiente) | Resuelve lo somero mucho mejor que gz | si el cliente tiene gradiometría: error somero con FTG vs gz |
  | Ensemble null-space (shuttle F8.1) | No acerca a la verdad: muestra el RANGO ("el cuerpo está entre 200 y 600 m") | ancho del ensemble vs la verdad — honestidad accionable |
- **B2 — PEDIR el dato que más aporta** (Nivel 2 de F11 — es un formulario, multiplica el valor):
  1. Sondajes con **densidad/susceptibilidad MEDIDA** por tramo (la restricción #1 de la literatura).
  2. Petrofísica de superficie (media/varianza por unidad → PGI).
  3. Mapeo geológico (contactos/fallas → superficies implícitas F7 que acotan geometría).
  4. Diseño de survey ANTES de medir (prevención: mostrar `observable_depth_max_m` como advertencia previa).
  - La UI lo pide con el **beneficio explícito**: *"con densidades medidas, el modelo queda anclado a valores reales."*
- **B3 — El bucle perforar → anclar → re-invertir como flujo de producto**: TQ ya tiene el ancla dura. El reframe medido: antes de perforar el ancla es tautológica; DESPUÉS del primer pozo es **calibración legítima** que propaga información real. Convertirlo en flujo explícito = también es el modelo de negocio del acompañamiento por-proyecto.

**Gate B (medible):** por CADA restricción, un número de mejora medido en benchmark con verdad (o un *"no mejora, documentado"* honesto). El presupuesto de error de la Parte A se **recalcula CON restricciones** → cuánto recortamos el error, con evidencia.

**Regla de oro de B (aprendida con cross-gradient):** ninguna restricción se cablea a producción ni se vende sin su número medido de mejora real.

## RESULTADOS MEDIDOS — Parte B, primera pasada MULTI-FÍSICA (2026-07-24)

Herramienta: `scripts/validation/multiphysics_gain.py`. Cuerpo sintético con contraste de **densidad Y susceptibilidad** a 500 m (donde grav-sola falla en profundidad) + un sondaje que lo intersecta. Dato generado con el motor en malla FINA (anti-inverse-crime), invertido en 5 configuraciones. **Números medidos, sin ajustar:**

| Config | Horizontal | Error profundidad | Veredicto honesto |
|---|---|---|---|
| **1. Grav-sola** | **43 m** ✓ | **438 m** ✗ | dónde SÍ, profundidad NO (masa apilada a 62 m) |
| **2. Mag-sola** | 345 m ✗ | **282 m** (mejor) | profundidad MEJOR (recupera a 218 m), pero horizontal PEOR (anomalía dipolar corrida a inclinación −55°, pide RTP) |
| **3. Joint grav+mag** (cross-gradient) | 46 m ✓ | **438 m** ✗ | **NO mejora la profundidad** — el modelo de densidad queda igual que grav-sola |
| **4. Grav + sondaje** (ancla dura) | **0 m** | **0 m** (recupera 500 m exacto) | fija la profundidad… pero solo EN el pozo (tautológico) |
| **5. Grav + mag + sondaje** | 0 m | 0 m | = grav+sondaje (el ancla domina) |

**Las tres conclusiones (directas y medidas):**
1. **Las físicas SÍ son complementarias:** la gravedad da el DÓNDE (43 m); la magnetometría tiene información de PROFUNDIDAD que la gravedad no tiene (recupera 218 m vs los 62 m apilados de la gravedad) — porque su kernel cae más rápido (1/r³) y su estructura dipolar restringe la profundidad. Es la razón de libro para combinar.
2. **PERO el joint cross-gradient (como está cableado) NO extrae esa combinación:** el modelo de densidad del joint quedó IGUAL que grav-sola en profundidad (438 m). El cross-gradient alinea ESTRUCTURA pero no transfiere la profundidad del mag a la gravedad. Confirma lo ya medido en DO-27. → **Es una oportunidad, no un callejón:** falta un mecanismo que sí meta la profundidad del mag (o de Euler) al modelo — a probar y MEDIR (mag-como-prior-de-profundidad, Gramian, PGI, o Euler; una iteración de cross-gradient no basta).
3. **El sondaje fija la profundidad EXACTO — pero solo donde perforas** (in-sample; el leave-one-out ya midió que NO predice entre pozos). Es CALIBRACIÓN legítima después de perforar, no predicción antes.

**Traducción a producto:** hoy, sin restricciones, vendes DÓNDE. Para vender algo de PROFUNDIDAD honesta hay dos caminos medibles: (a) meter la profundidad del **mag/Euler** al modelo con un mecanismo que de verdad funcione (el cross-gradient de 1 iteración no lo hace) → si mejora medido, es oro; (b) el bucle **perforar→anclar→re-invertir** (calibración post-pozo, que además es tu modelo de negocio por-proyecto). El siguiente experimento de B es medir (a): mag/Euler como prior de profundidad, antes/después, en este mismo banco.

### Experimento clave de B — PRIOR DE PROFUNDIDAD (2026-07-24): ✅ FUNCIONA

`scripts/validation/depth_prior_experiment.py`. Como el cross-gradient NO transfiere la profundidad, probamos meterla DIRECTO con un prior: *"una física independiente (Euler/mag) dice que el cuerpo NO está somero → se prohíbe contraste por encima de ese horizonte"* (ancla dura a densidad-base en las celdas someras, hook EXISTENTE del motor). Cuerpo a 500 m (techo real 350 m):

| Prior (horizonte) | Horizontal | Error profundidad | vs baseline |
|---|---|---|---|
| **Baseline (sin prior)** | 43 m | **438 m** | — |
| **Euler-perfecto (piso 350 m)** | **11 m** | **62 m** | **7× mejor** |
| Euler-conservador (piso 300 m) | 88 m | 188 m | 2.3× mejor |
| Mag-imperfecto (piso 200 m) | 88 m | 188 m | 2.3× mejor |
| Malo (piso 100 m, control) | 117 m | 312 m | 1.4× mejor |

**Conclusión medida:** inyectar una profundidad independiente **SÍ arregla la profundidad de la gravedad** (438→62 m con buen prior) y hasta mejora el horizontal (43→11 m). La mejora es MONÓTONA con la calidad del prior → hay que sacarlo de **Euler** (F2B, 0% error en esfera/dipolo), no del centroide crudo del mag. Este es el mecanismo que el cross-gradient NO daba. **Camino a la profundidad, medido: Euler-como-prior (funciona), NO cross-gradient (no funciona).**

### Cierre del círculo con Euler REAL (2026-07-24): el mecanismo funciona, el AUTO-SOURCE no (aún)

`scripts/validation/euler_depth_prior_loop.py`. Se corrió el servicio Euler REAL de F2B sobre los datos (grav SI=2 y mag SI=3, survey denso 24×24) para SACAR la profundidad automáticamente y alimentar el prior. Resultado MEDIDO, honesto:
- **Euler-grav → z=71 m** y **Euler-mag → z=65 m**, para un cuerpo a **500 m**. Ambos grossly SOMEROS.
- → El prior derivado no ancló nada útil (piso ~46-65 m < capa somera) y la profundidad no mejoró (312→312 m). *El horizontal sí mejoró (70→18 m).*

**Por qué:** Euler resuelve bien fuentes SOMERAS-moderadas (F2B midió 0% de error a 150-200 m) pero **subestima fuertemente las fuentes PROFUNDAS** (anomalía ancha y suave → gradientes chicos → z espuria somera, sensible al ruido). **Catch-22 medido:** el prior de profundidad ayuda MÁS a los cuerpos profundos (donde la gravedad falla), pero ahí es justo donde Euler TAMBIÉN falla en dar la profundidad. La gravedad no puede auto-arreglarse la profundidad ni vía Euler.

**Conclusión honesta de B (el mapa real, medido):**
1. El **mecanismo** de prior de profundidad FUNCIONA (438→62 m con buen prior). ✅ Es un hook aditivo (usa `boreholes`, no toca la física validada).
2. La **fuente automática** de esa profundidad es el problema: Euler falla en profundo; el cross-gradient no la transfiere; el mag inversión la mejora parcial (218 m vs 62 m) pero no la clava.
3. La fuente **confiable** de profundidad hoy es un **sondaje** (la clava exacto, pero solo donde perforas = calibración post-pozo), o una estimación independiente que traiga el consultor (sísmica, pozo cercano, su propia interpretación).

**Decisión de ingeniería (disciplinada):** NO cablear auto-Euler→prior (medido poco confiable en profundo). SÍ empaquetar el mecanismo probado como servicio aditivo y tested (`depth_prior_service`) que constriñe la gravedad dado un horizonte de profundidad de una **fuente confiable** (sondaje / estimación del usuario), con el caveat honesto. Fuente automática confiable de profundidad = trabajo futuro medible (Euler solo somero; espectral; mag-inversión como prior suave; nuevas físicas).

### Punto 1 — FUENTE de profundidad confiable para profundo (2026-07-24): ✅ el ESPECTRO RADIAL

`scripts/validation/depth_source_comparison.py` (dato analítico esfera/dipolo, escala-invariante). Euler afinado (ventana grande + umbral estricto) + espectro radial (F2B), a 3 profundidades:

| Profundidad real | Euler-grav | Euler-mag | **Espectro-grav** | Espectro-mag |
|---|---|---|---|---|
| 300 m | 205 | 247 | **274** | 202 |
| 500 m | 266 (satura) | 393 | **419** | 312 |
| 700 m | 251 (satura) | 498 | **564** | 450 |

**El espectro radial de potencia (`radial_power_spectrum`, F2B) es la mejor fuente:** sigue la profundidad real (274/419/564 para 300/500/700 m; ~15% bajo pero MONÓTONO), es global/robusto (no ventana), y **funciona solo con gravedad**. Euler-grav SATURA (~250 m, ciego a lo profundo — por eso el auto-Euler previo daba 65-71 m). Euler-mag es buen complemento cuando hay magnetometría. → **Fuente de profundidad para el prior = espectro radial (grav); Euler-mag si hay mag.** El servicio `depth_prior_service` es agnóstico a la fuente, así que esto se le enchufa directo.

### Punto 2 — CADENA COMPLETA validada sobre verdad conocida (2026-07-24): ✅ 7–18× mejor

`scripts/validation/depth_prior_endtoend.py`: dato gravimétrico → **espectro REAL (F2B)** estima la profundidad → `recommend_depth_floor` (×1.15 corrección + 0.7 margen) → `build_depth_floor_prior` → **motor REAL** invierte con y sin prior. 3 profundidades:

| Profundidad real | Espectro estimó | Error prof. (baseline → prior) | Horizontal (baseline → prior) |
|---|---|---|---|
| 300 m | **297 m** (99%) | 112 → **12 m** (9×) | 5.5 → 1.0 m |
| 500 m | **488 m** (98%) | 1135 → **62 m** (18×) | 1288 → 2.2 m |
| 700 m | **647 m** (92%) | 987 → **137 m** (7×) | 466 → 33 m |

**Con componentes de producción y sin trampa** (la profundidad salió del dato vía el espectro, no fue puesta a mano), el error de profundidad de la gravedad cae **7–18×** y el horizontal también. La cadena funciona: espectro (fuente confiable de profundidad) → prior → motor.

**Caveats honestos:** (a) los benchmarks externos (DO-27) son SOMEROS → no ejercitan el régimen profundo; la validación es sobre sintético con verdad conocida a 3 profundidades. (b) **PERFORMANCE:** la inversión anclada fue MUY lenta (decenas de min/caso) por las ~324 columnas × capas someras ancladas — antes de cablear (Punto 3) hay que reemplazar el ancla-por-columna por una MÁSCARA de bounds (density_max=base en celdas someras), mucho más barata y equivalente.

### Punto 3.1 — eficiencia + librería completa (2026-07-24)

- **Hallazgo (medido, corrige mi hipótesis):** la MÁSCARA de bounds (`lithology_bounds` con box despreciable) es **19× MÁS LENTA** que el ancla dura (523 s vs 27 s a 144 estaciones, mismo error de profundidad 62 m). El ancla dura ELIMINA variables (sistema más chico → rápida); la máscara las conserva y clampa (solver acotado lento). → Se DESCARTÓ la máscara. **El ancla dura ya es el mecanismo eficiente.** La lentitud del endtoend era el survey de 576 estaciones (para el espectro), no el ancla. Fix real: **desacoplar** — grilla densa para el espectro (FFT barata), survey normal para invertir (ancla dura, rápida).
- **Librería COMPLETA (aditiva, tested, NO toca motor validado ni frontend):** `services/depth_prior_service.py` ahora tiene `recommend_depth_floor` + `build_depth_floor_prior` + **`estimate_depth_prior_from_grid`** (cadena automática: grilla → espectro F2B → piso → prior). `tests/test_depth_prior_service.py`: 6 unit rápidos verdes + 1 `validation` de ganancia física.

### Punto 3.2 — flag opt-in CABLEADO al motor (2026-07-24): ✅ (autorización total de Martín)

Cambio mínimo, guardado, **default OFF = byte-idéntico**:
- **Esquema** (`GeophysicsInvertInput`): `enable_depth_prior: bool = False` + `depth_prior_safety_fraction: float = 0.7`.
- **Flujo** (`run_geophysics_inversion`, ruta gravimétrica): UN bloque guardado (`if enable_depth_prior:`) que grilla el survey → **espectro REAL** estima la profundidad → `depth_prior_service` arma el ancla → la suma a `boreholes_arr` (fuerza ancla dura solo si no hay sondajes reales). Envuelto en try/except → NUNCA rompe la inversión. **No toca el solve validado** (sólo puebla el contrato `boreholes` existente).
- **Servicio**: `estimate_depth_prior_from_stations` (survey disperso → grid_scattered → espectro → prior).
- **Tests**: 7 unit rápidos verdes + 2 `validation` (INTEGRACIÓN en el flujo real: con flag ON la capa somera queda sin contraste, con OFF no — **PASS 39 s**; + ganancia física). Motor validado y frontend INTACTOS salvo este bloque aditivo default-OFF.

**Pendiente de B (iteraciones propias):** (3.3) UI — campo opt-in en el panel (frontend, iteración aparte por la regla de oro backend≠frontend); (4) [PUNTO 4] W_z inerte + PGI/Gramian; luego Parte C.

---

# PARTE C — Red-team: *romperlo nosotros antes de que lo rompan*

**Objetivo:** antes del gate de venta, agotar sistemáticamente los modos de falla. El enemigo #1 NO es el crash — es el **número corrupto con cara de bueno** (el doble-Bouguer y la coma-decimal de junio eran exactamente eso).

## Trabajo

- **C1 — Caza de corrupción silenciosa** (MÁXIMA prioridad; extiende F8): generar el dato más feo posible (formatos de instrumento raros, unidades ambiguas, preámbulos, filas rotas, CRS mal declarado, decimales europeos, negativos, huecos) y verificar el invariante duro: **o sale un modelo válido, o un error claro en español — nunca un número silenciosamente equivocado con sello de calidad**. Métrica: `0` corrupciones silenciosas en N miles de casos generativos + corpus real.
- **C2 — Red-team de física** (el más importante para la confianza): intentar ACTIVAMENTE forzar al motor a dar un **target confiado donde el dato no resuelve** (null-space, bajo el horizonte DOI, cuerpo profundo con cobertura pobre). Si se logra sacar un "HIGH" en zona no-resoluble → **es un bug de honestidad** → se tapa (la trilogía B1/B2/B3 debe degradarlo a LOW). Es el escudo legal del mundo JORC.
- **C3 — Verificación cruzada con otras IAs** (para lo caro, no para todo): protocolo — se pide segunda opinión de otra IA cuando (a) hay una afirmación de física NUEVA, (b) una bifurcación de arquitectura, (c) un número que irá a un informe que **alguien firma**. Se comparan y se concilian; si difieren, se MIDE para desempatar. Barato, y sube la certeza donde importa.
- **C4 — Exposición a dato REAL** (lo que ningún test sintético reemplaza, y donde comprimimos de verdad los 20 años): 1–2 consultores reales intentan romperlo con SU dato de campo. Cada fricción → lista priorizada sobre cualquier feature nueva.

**Gate C (medible):** (1) K rondas adversariales sin una sola corrupción silenciosa nueva; (2) el reporte honesto resiste el intento de extraerle un target falso en null-space; (3) al menos 1 consultor real pasó su dato de punta a punta sin sorpresa catastrófica.

---

# ORDEN, TIEMPO Y HONESTIDAD

**Orden:** A → (B ∥ C). Primero saber DÓNDE estamos (A); luego mejorar (B) y romper (C) en paralelo. Todo antes del gate de venta de F10.

**Lo que probablemente NO va a cambiar (y está bien):**
- La **profundidad** seguirá siendo el límite duro de la gravedad-sola. La venta es **targeting horizontal + el gabinete automatizado + el reporte honesto que un QP puede firmar** — no "ver la realidad" ni "estimar recursos".
- El objetivo de la Parte B no es "eliminar" el error, es **recortarlo con datos** y **decir cuánto** recortamos. Un cliente que entiende exactamente qué resuelve su dato confía más que uno al que le prometen magia.

**El diferenciador de verdad (por qué no nos demoramos 20 años):** IA + **medición implacable** + **red-team propio** + **exposición temprana a dato real**. No porque la IA sea mágica —hoy mismo se equivocó y lo cazó la medición— sino por la disciplina de nunca creerle a nadie sin oráculo.
