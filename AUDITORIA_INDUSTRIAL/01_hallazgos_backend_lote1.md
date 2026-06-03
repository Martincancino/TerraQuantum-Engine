# DIGEST AUDITORIA — 11 subsistemas OK: ['grav-core', 'mag-joint', 'geophysics-orchestrator', 'csv-import', 'block-model-export', 'spatial-georef', 'economics-mine', 'api-app-schemas', 'security-config', 'test-quality', 'fe-render']
TOTAL findings por severidad: {'P1': 46, 'P2': 65, 'P3': 34, 'P0': 9}

## grav-core  (P0:0 P1:3 P2:7 P3:2) archivos:3
### [P1] grav-core-01 | dim:2 FISICA/MATEMATICA, 8 FALLBACK SILENCIOSO | conf:alta
**density_min=2.6 por defecto prohibe recuperar contrastes negativos (colapso fisico unilateral)**
- file: terraquantum-backend/exploration/gravimetry.py:925-926, 1201-1202, 1446-1454
- impacto: self.base_density=2.6 (linea 361) y density_min=2.6 son iguales, por lo que el contraste recuperado se acota a [0, 1.6] t/m3. La inversion NO PUEDE recuperar cuerpos de baja densidad (cavidades, alteracion argilica, zonas de baja densidad), que son objetivos legitimos en gravimetria. El bound se vende como 'petrofisico configurable' pero su default convierte el problema en non-negativity unilateral silencioso. El default se propaga desde el schema de la API (geophysics_service.py:1526) hasta produccion.
- fix: Permitir density_min < base_density por defecto (p.ej. 2.0) o desacoplar el bound del contraste; documentar explicitamente que el default actual elimina anomalias negativas y advertir en solver_meta cuando una fraccion alta satura en density_min.
- VERIFICACION: incierto (sev->) :: verificacion fallo
### [P1] grav-core-02 | dim:2 FISICA/MATEMATICA | conf:media
**Depth-weighting Li&Oldenburg aplicado SOLO a la suavidad (Laplaciano), no a la smallness/damp -> sesgo de profundidad no corregido en el termino que controla amplitud**
- file: terraquantum-backend/exploration/gravimetry.py:1223-1232, 1329-1342, 1403
- impacto: El depth weighting Li&Oldenburg (1996/1998) debe entrar en el termino de modelo (smallness/Wm) para compensar el decaimiento del kernel y evitar que la masa se acumule cerca de la superficie. Aqui w_reg solo pondera el operador de RUGOSIDAD (Laplaciano). El termino smallness (damp=lambda_mag y el bloque diferencial) es UNIFORME en profundidad. Resultado: el clasico bug de que la densidad recuperada se concentra en celdas someras no queda corregido por el mecanismo estandar; la presencia de Ws (column scaling) lo mitiga parcialmente pero no es equivalente al w=(z+z0)^(-beta/2) de Li&Oldenburg sobre el modelo.
- fix: Aplicar el peso de profundidad al termino de smallness/damp (multiplicar _w_small y el _eye_lam por w_depth^(1/2) por celda), no solo al Laplaciano, siguiendo Li&Oldenburg estricto.
- VERIFICACION: incierto (sev->) :: verificacion fallo
### [P2] grav-core-03 | dim:1 CORRECTITUD, 2 FISICA | conf:media
**lambda_spatial usa n_active pero el sistema se resuelve sobre _n_active_sol (dominio observable podado) -> regularizacion mal escalada**
- file: terraquantum-backend/exploration/gravimetry.py:1235, 1115-1149
- impacto: Cuando hay celdas muertas (_n_dead>0), lambda_spatial se calcula con el n_active completo (mas grande) mientras el sistema efectivo tiene _n_active_sol columnas. El balance datos/regularizacion queda inconsistente respecto al numero real de incognitas, sesgando la solucion (sub- o sobre-regularizada) de forma dependiente de cuantas celdas se podan, que a su vez depende de la geometria. No es determinista respecto al caso fisico.
- fix: Recalcular lambda_spatial con _n_active_sol despues de la poda R-05, o documentar y fijar la convencion; aplicar el mismo arreglo en select_lambda_lcurve (linea 583) y select_lambda_chi2_target (linea 823).
### [P2] grav-core-04 | dim:1 CORRECTITUD, 2 FISICA, 9 DUPLICADO DIVERGENTE | conf:media
**L-Curve mide roughness con Laplaciano SIN depth-weighting; el solver final SI lo aplica -> el lambda 'optimo' no corresponde al operador realmente usado**
- file: terraquantum-backend/exploration/gravimetry.py:600-609, 579-580
- impacto: La esquina de la L-curve se calcula sobre una metrica de roughness (||L_active@m||) distinta del termino de regularizacion realmente penalizado (||W_m@m||, con depth weighting). El lambda seleccionado es por tanto sub-optimo / inconsistente con solve_inversion_lsqr, que ademas usa lambda_mag como damp distinto. Selecciona regularizacion para un problema que no es el que luego se resuelve.
- fix: Calcular roughness_norm con W_m (depth-weighted) consistente, y dejar claro que el damp barrido (lam) corresponde a lambda_mag/smallness, no a lambda_spatial.
### [P1] grav-core-05 | dim:3 ROBUSTEZ, 8 FALLBACK SILENCIOSO | conf:alta
**Misfit_percent y score retornan 0.0 / 1.0 ante norma observada nula o error nulo -> resultado degenerado se reporta como ajuste perfecto**
- file: terraquantum-backend/exploration/gravimetry.py:1480-1483, 1495-1502
- impacto: Si g_observed es todo cero o degenerado (observed_norm=0), misfit_percent=0.0% (parece ajuste PERFECTO) en vez de fallar. Igual el score: si max_voxel_error<=0 todas las celdas reciben score=1.0 (objetivo maximo en todas partes). Un input vacio/degenerado produce un resultado plausible y optimista en lugar de un error honesto. Es exactamente el pecado capital de fallback silencioso descrito en el rubro.
- fix: Cuando observed_norm<=0 o max_voxel_error<=0, marcar el resultado como degenerado (NaN en misfit/score o levantar excepcion), no devolver 0%/1.0 que simula exito.
- VERIFICACION: incierto (sev->) :: verificacion fallo
### [P2] grav-core-06 | dim:2 FISICA, 3 ROBUSTEZ | conf:alta
**_sigma_adaptive usa solo data_range positivo de max-min; ante d_obs constante o anomalia negativa pura el piso de ruido colapsa el peso**
- file: terraquantum-backend/exploration/gravimetry.py:28-30
- impacto: Si todos los g_observed son iguales (data degenerado), data_range=1e-30 y sigma=0.02*|d|; si ademas d=0 -> sigma=1e-30 -> Wd=1/sigma=1e30, condicionamiento catastrofico. El switch a sigma adaptivo se activa SOLO cuando noise_floor==0.02 and noise_pct==0.02 (igualdad de floats exacta, linea 1169) — una comparacion fragil: cualquier caller que pase 0.020000001 obtiene la rama legacy con noise_floor en unidades crudas. La eleccion del modelo de ruido depende de igualdad exacta de floats, no de intencion.
- fix: Usar un flag explicito (use_adaptive_sigma: bool) en vez de comparar floats por igualdad; acotar Wd con un techo y validar data_range>0 real.
### [P2] grav-core-07 | dim:2 FISICA (ejes intercambiados) | conf:media
**Convencion de ejes: y=profundidad, x y z ambos horizontales sin distincion Norte/Este -> ambiguedad que invita a intercambio silencioso**
- file: terraquantum-backend/exploration/gravimetry.py:93-98, 117, 148
- impacto: El kernel calcula g_y (componente vertical) usando y como profundidad, lo cual es coherente internamente. Pero x y z son ambos 'horizontal' sin definir cual es Norte y cual Este. La MEMORY del proyecto documenta que el motor magnetico usa x=Norte/z=Este; si el caller mezcla convenciones entre gravimetria y magnetometria (joint inversion en joint_inversion.py:380) los cuerpos quedaran rotados 90 grados sin error. No hay assert que ligue x/z a un sistema georreferenciado.
- fix: Documentar y validar explicitamente cual eje es Norte/Este, y verificar consistencia con el kernel magnetico antes de la inversion conjunta (cross-gradient asume mallas alineadas).
### [P3] grav-core-08 | dim:6 RENDIMIENTO, 3 ROBUSTEZ | conf:alta
**Cache de kernel valida geometria pero NO el cutoff/threshold ni dtype; ademas imprime a stdout en hot path**
- file: terraquantum-backend/exploration/gravimetry.py:173-185, 184, 312, 184
- impacto: El geom_key incluye dx/dy/dz/cutoff y shapes, y luego valida arrays con array_equal — correcto. Pero todo el path imprime con print() (no logger) en cada construccion/hit; en L-curve (20 trials) y chi2-scan estos prints saturan stdout y, si stdout se captura como JSON de respuesta API, contaminan la salida. Relacionado con la clase de bug 'no llega JSON valido': el motor escribe decenas de lineas a stdout por run.
- fix: Reemplazar print() por logger.debug en todo gravimetry.py; nunca escribir a stdout en un proceso cuyo stdout pueda ser canal de datos.
### [P2] grav-core-09 | dim:8 FALLBACK SILENCIOSO, 7 REPRODUCIBILIDAD | conf:media
**checkerboard_test fuerza pearson_r=0.0 (PASS-bypass) y SNR=inf/-inf en casos degenerados; el veredicto QA puede pasar con datos triviales**
- file: terraquantum-backend/exploration/checkerboard_test.py:170-176, 182-185, 197-202
- impacto: El test de QA que supuestamente valida que el motor 'aprende geometria' devuelve metricas fabricadas (0.0, inf) en bordes en vez de marcar el caso como invalido. Un est_density constante (colapso a fondo uniforme — el fallo central que el test debe detectar) da ec.std()<1e-15 -> pearson_r=0.0 -> FAIL correcto, PERO el caso n_active<4 retorna pearson_r=0.0 que se compara con >=0.4 y marca FAIL silencioso sin distinguir 'colapso' de 'grilla muy chica'. El SNR inf enmascara recuperacion perfecta sospechosa.
- fix: Devolver pearson_r=NaN y un flag 'invalid_case' en degeneraciones, y que el veredicto distinga FAIL-por-colapso de SKIP-por-input-insuficiente.
### [P3] grav-core-10 | dim:9 CODIGO/DOC DIVERGENTE | conf:alta
**Docstrings desincronizados con defaults reales (n_trials, lambda_mag) -> deuda que engana al operador**
- file: terraquantum-backend/exploration/gravimetry.py:511, 488
- impacto: El operador que lea el docstring cree que el barrido usa 5 lambdas cuando usa 20; menor, pero en software industrial la doc de un parametro de regularizacion debe ser exacta.
- fix: Sincronizar docstrings con las firmas reales.
### [P2] grav-core-11 | dim:6 RENDIMIENTO/ESCALABILIDAD | conf:media
**engine.py (Lerchs-Grossmann): doble loop Python add_tedge/add_edge sobre todos los nodos/arcos -> O(nnz) en Python puro, no escala a millones de bloques (contradice el comentario)**
- file: terraquantum-backend/engine.py:105-116, 112-113
- impacto: El comentario en build_sparse_graph dice 'soportar millones de bloques sin agotar la RAM', pero optimize_with_maxflow itera en Python sobre cada nodo y cada arco (nnz puede ser decenas de millones). Esto es O(nnz) interpretado en Python — lentisimo. Ademas nonzero() materializa dos arrays grandes y add_edge se llama uno por uno. La construccion CSR vectorizada se desperdicia al volcarla en un loop Python.
- fix: Usar la API batch de maxflow (add_grid_edges / add_edges vectorizado) o pasar arrays directamente; evitar el zip() Python sobre millones de arcos.
### [P2] grav-core-12 | dim:1 CORRECTITUD (condicion potencialmente invertida) | conf:baja
**engine.py: get_segment==0 define 'mined' sin verificar convencion source/sink; posible mascara invertida**
- file: terraquantum-backend/engine.py:105-109, 122
- impacto: La asignacion source/sink (capacidad a source = weight para bloques de valor positivo) y la interpretacion get_segment()==0 como 'minado' deben ser consistentes con la convencion de PyMaxflow (segment 0 = source side). Si la libreria define segment 0 como el lado del SINK, la mascara de bloques extraidos queda invertida (se 'minan' los bloques esteriles y se dejan los de mena) sin ningun error. No hay test de signo ni assert que valide que el valor total extraido es >=0.
- fix: Anadir un assert/test: el pit optimo debe tener valor total >= 0 y >= cualquier sub-pit; validar la convencion de get_segment contra un caso trivial conocido (un bloque positivo enterrado bajo esteril).

## mag-joint  (P0:0 P1:2 P2:5 P3:4) archivos:3
### [P1] joint-xgrad-scaling-asymmetry-01 | dim:2 (Física/Matemática) y 9 (Lógica clonada que diverge) | conf:media
**El bloque cross-gradient se escala con transformadas DISTINTAS en cada física (Ws vs Wz_inv) → acoplamiento estructural asimétrico**
- file: terraquantum-backend/services/joint_inversion.py:455, 465 (inyección) vs gravimetry.py:1303 y magnetometry.py:626
- impacto: El esquema de Gallardo–Meju exige que la penalización cross-gradient acople AMBOS modelos con el mismo peso efectivo por celda. Como Ws (gravedad) y Wz_inv (magnético) son transformadas físicamente distintas (Ws amplifica celdas profundas por su columna casi-nula, Wz_inv las amplifica por ley de potencia controlada), el MISMO lambda_cross produce fuerzas de acoplamiento estructural radicalmente distintas en gravedad vs magnetometría. El resultado conjunto queda sesgado hacia la estructura del modelo cuya transformada amplifica más, en vez de un acoplamiento simétrico. No falla ruidosamente: converge y reporta E_norm, pero la estructura compartida está mal ponderada.
- fix: Escalar el bloque cross-gradient con un peso COMÚN e idéntico en ambos motores (p.ej. inyectar el bloque ya en espacio de la variable transformada de cada motor con un factor de normalización equivalente, o normalizar B por celda con la misma métrica antes de pasarlo), de modo que lambda_cross tenga el mismo significado físico en los dos pasos.
- VERIFICACION: incierto (sev->) :: verificacion fallo
### [P1] joint-degenerate-block-fallback-02 | dim:8 (Fallbacks silenciosos que fingen resultados) | conf:media
**El empaquetado fabrica un bloque 'anómalo' no vacío aunque la inversión sea degenerada (cuts mínimos absolutos)**
- file: terraquantum-backend/services/joint_inversion.py:514-516, 525-526
- impacto: Una inversión conjunta degenerada (anomalía espuria, sobre-regularizada, o datos casi planos) igualmente produce `voxels` no vacío y un `best_target` con coordenadas/valores plausibles. El test sintético (_self_test) y las aserciones (`len(result['voxels']) > 0`) PASAN por construcción, enmascarando que el modelo no recuperó nada físico. Es el pecado capital del proyecto: resultado vacío que parece válido.
- fix: Reemplazar los pisos absolutos por umbrales relativos al rango real de cada campo Y exigir una amplitud mínima de señal (p.ej. percentil + chequeo de SNR/misfit). Si max(abs_contrast) y max(m_chi) no superan un mínimo significativo, devolver bloque vacío con bandera explícita de 'sin anomalía detectable' en vez de rellenar con ruido.
- VERIFICACION: incierto (sev->) :: verificacion fallo
### [P2] joint-base-rho-leak-into-keep-03 | dim:1 (Correctitud) y 8 (Fallback) | conf:media
**susc_cut/keep usan m_chi absoluta (base_susc=0, ok) pero combined normaliza por max sin guardia de signo; densidades por debajo de base no penalizadas**
- file: terraquantum-backend/services/joint_inversion.py:513-524
- impacto: Un déficit de masa (contraste negativo grande) se ranquea como target de interés igual que un exceso, mezclando señales geológicamente opuestas en el score combinado que consume Gemini/frontend y en best_target. Para un público minero (buscando cuerpos densos/magnéticos) esto introduce falsos positivos.
- fix: Decidir explícitamente la convención: si el objetivo son excesos de masa, usar np.clip(rho_contrast, 0, None) para el score (como sí se hace en centroid_mass línea 554), o documentar y separar excesos/déficits. Mantener coherencia entre keep, combined y centroid_mass.
### [P2] joint-cond-nan-in-history-04 | dim:7 (Reproducibilidad/Provenance) y 3 (Robustez) | conf:alta
**cond_A_magnetic/gravity quedan NaN en el history y manifest cuando el bounded solver está activo (default en producción)**
- file: terraquantum-backend/exploration/magnetometry.py:664, 682, 696, 750
- impacto: El manifiesto de provenance industrial (HITO 2) registra cond(A)=NaN como diagnóstico de calidad del solver en el modo POR DEFECTO de producción, perdiendo el indicador de estabilidad numérica. El warning de cond(A)>1e12 (control de calidad) queda muerto. Provenance que finge trazabilidad sin el dato clave.
- fix: Cuando se usa lsq_linear/TRF, estimar cond(A) por separado (p.ej. svds o cond del sistema aumentado) o registrar explícitamente 'cond_A: not_computed (bounded solver)' en vez de NaN, y guardar el flag de qué solver se usó.
### [P3] joint-route-empty-list-magnetic_nt-05 | dim:4 (Contratos de API) y 1 (Correctitud) | conf:alta
**Ruteo por magnetic_nt usa truthiness: lista vacía [] cae a gravedad silenciosamente; g vacío/0 nunca lo detecta el motor magnético aislado**
- file: terraquantum-backend/services/geophysics_service.py:1904-1912
- impacto: Un cliente que envía magnetic_nt=[] (p.ej. campo presente pero sin datos) obtiene una inversión gravimétrica pura sin error ni advertencia, en vez de un 422. Contrato ambiguo entre None/[]/ceros.
- fix: Distinguir explícitamente: magnetic_nt None → gravedad; [] o longitud≠observations → 422; ceros → mensaje claro. Validar la longitud antes del ruteo.
### [P2] joint-silent-except-swallow-06 | dim:3 (Robustez/excepciones tragadas) y 8 (Fallback) | conf:alta
**Cadena de try/except 'nonfatal' traga errores de persistencia, manifest, clustering y Gemini sin propagar al status del run**
- file: terraquantum-backend/services/joint_inversion.py:313-314, 629-630, 643-644, 691-692, 721-723, 735-743, 748-749
- impacto: Si la persistencia Parquet del bloque conjunto falla, o el manifest de provenance no se escribe, o el clustering revienta, el run se marca 'done' con éxito y devuelve voxels en memoria, pero NO hay archivo reproducible en disco ni audit trail. El `except: pass` de _update oculta incluso fallos del tracking de progreso. Para software 'industrial' con provenance, perder el Parquet/manifest silenciosamente es grave.
- fix: Separar fallos verdaderamente no-fatales (Gemini, clustering descriptivo) de los que comprometen reproducibilidad (Parquet, manifest): estos últimos deben marcar el run como 'done_with_warnings' o degradar el status y exponer el error en la respuesta. Eliminar el `except: pass` mudo de _update (al menos loggear).
### [P3] mag-tmp-test-debris-07 | dim:9 (Código muerto/_tmp) | conf:alta
**Archivo _test_mag_route_tmp.py en la raíz del backend: dead code/test debris versionado**
- file: terraquantum-backend/_test_mag_route_tmp.py:1-52
- impacto: Confusión de mantenimiento; además referencia un contrato (`res['report']['solver']['cond_A']`, `best_target['susceptibility']`) que difiere del contrato joint (`field.field_unit_vector_xyz`, `susceptibility_si`), evidenciando divergencia de shapes entre rutas. Si el contrato cambia, este test queda obsoleto sin que CI lo cubra.
- fix: Mover a tests/ con nombre estable o eliminar. Unificar el contrato de salida entre run_magnetic_inversion y run_joint_inversion (ambos exponen susceptibilidad pero con claves distintas: 'susceptibility' vs 'susceptibility_si').
### [P2] joint-contract-divergence-best_target-08 | dim:4 (Contratos de API) y 9 (Lógica duplicada divergente) | conf:media
**best_target/voxels divergen de forma entre ruta magnética aislada y ruta conjunta (susceptibility vs susceptibility_si, density ausente/presente)**
- file: terraquantum-backend/services/joint_inversion.py:529-548 (joint) vs geophysics_service.py:1886-1891 (magnético aislado)
- impacto: El frontend/consumidor que reciba la respuesta de run_geophysics_inversion no puede asumir una forma estable de best_target/voxels: depende de si se ruteó a joint o a magnético aislado, y las claves de susceptibilidad difieren (susceptibility vs susceptibility_si). Esto rompe el contrato frontend↔backend de forma intermitente según el input.
- fix: Definir un schema Pydantic de salida único (GeophysicsVoxel ya existe en schemas) y forzar response_model en ambas rutas, normalizando nombres de campo (elegir susceptibility_si en todas). El api/geophysics_api.py no declara response_model.
### [P2] joint-lambda-mag-shared-both-physics-09 | dim:2 (Física/regularización mal calibrada) | conf:media
**params.lambda_mag se usa como regularización smallness de AMBAS físicas en joint (gravedad y magnetometría) pese a escalas distintas**
- file: terraquantum-backend/services/joint_inversion.py:375-376
- impacto: Solo los fallbacks (lambda_mag=0) usan valores distintos (1e-5 grav vs 1e-4 mag); con cualquier lambda_mag>0 explícito ambos comparten el mismo peso de norma mínima, aunque las magnitudes naturales de ρ y χ difieren órdenes. Esto regulariza de más o de menos uno de los dos campos, sesgando el balance del joint.
- fix: Exponer lambdas independientes (lambda_grav, lambda_susc) en el schema, o derivar lam_m de lam_g escalado por el rango típico de cada propiedad. El nombre 'lambda_mag' compartido para gravedad es además confuso.
### [P3] mag-anchor-overlap-stale-tol-10 | dim:1 (Correctitud) y 3 (Robustez) | conf:baja
**Anclaje de sondajes magnéticos: tolerancia xz = dx/2 puede asignar un intervalo a múltiples columnas o a ninguna en malla regional gruesa**
- file: terraquantum-backend/exploration/magnetometry.py:489-506
- impacto: En mallas regionales (block_size grande, p.ej. Bushveld con block ~1552m) un sondaje fuera de toda celda (continue, línea 494) se descarta SILENCIOSAMENTE sin avisar al usuario que su dato de calibración no se usó; o se duplica en dos columnas. Anclaje petrofísico fantasma.
- fix: Usar asignación a la celda MÁS CERCANA (argmin de distancia xz) en vez de máscara por tolerancia con <=, y registrar/avisar cuántos sondajes quedaron fuera de la malla en solver_meta para que no se pierdan en silencio.
### [P3] joint-no-noise-floor-validation-11 | dim:2 (Física) y 3 (Robustez) | conf:baja
**Joint no valida que sensor_coords estén FUERA de los vóxeles (dipolo asume sensor externo); sensores dentro del modelo dan kernel singular suavizado por eps**
- file: terraquantum-backend/exploration/magnetometry.py:139-141, 203, 206
- impacto: Si un usuario envía sensores cuya posición coincide con celdas del modelo (datos downhole, o coordenada y mal interpretada), el factor (3fdot²-r²)/r⁵ explota/diverge y eps solo evita la división por cero, produciendo pesos enormes sin avisar. Resultado físicamente sin sentido que parece converger.
- fix: Validar en build_sparse_kernel/joint que la distancia mínima sensor-celda supere ~dy/2, o rechazar con 422 si algún sensor cae dentro de la huella vertical del modelo.

## geophysics-orchestrator  (P0:0 P1:7 P2:5 P3:3) archivos:2
### [P1] grav-fallback-01 | dim:8 (fallback silencioso que finge resultado) / 1 (correctitud) | conf:alta
**params.depth ('target de exploración') no afecta NADA físico: solo es un guard y metadato**
- file: terraquantum-backend/services/geophysics_service.py:227-232, 240-256, 1966-1983
- impacto: El usuario cree que 'depth' (target de exploración) controla a qué profundidad se invierte. En realidad la profundidad del modelo la fija ny*block_size; 'depth' es decorativo. Un depth menor al dominio no recorta nada; el FOCO 'depth=L_max/3 y caps' vive en gravimetry.py/focusing.py, no en este orquestador. Falsa sensación de control de profundidad.
- fix: O bien derivar ny/block_size desde depth (scale-aware real en el orquestador), o documentar explícitamente en el payload que depth es solo administrativo y no condiciona la malla, y emitir warning si depth << dominio modelado.
- VERIFICACION: incierto (sev->) :: verificacion fallo
### [P1] grav-fallback-02 | dim:8 (fallback silencioso) | conf:alta
**build_best_target usa density=2.6 por defecto (el pecado capital: default oculta dato faltante)**
- file: terraquantum-backend/services/geophysics_service.py:952-959, 956
- impacto: Si un vóxel no tiene 'density' o es None, se sustituye por 2.6 → contraste 0 → contribuye 0 al ranking, enmascarando silenciosamente celdas degeneradas en vez de fallar. El 'mejor target' puede salir de un conjunto donde el contraste real es indistinguible del relleno base_density=2.6. El default 2.6 es exactamente el antipatrón citado en el rubro.
- fix: No usar default 2.6; filtrar explícitamente vóxeles con density is None / no finita antes del max y, si no queda ninguno, retornar None honestamente.
- VERIFICACION: incierto (sev->) :: verificacion fallo
### [P1] grav-fallback-03 | dim:8 (finge resultado) / 2 (normalización que colapsa rango) | conf:alta
**cutoff_density adaptativo (mean+0.5σ) fuerza ~30% de anomalías sin importar si hay señal real**
- file: terraquantum-backend/services/geophysics_service.py:2581-2600
- impacto: Para datos regionales (block>500m) el cutoff se autoajusta para SIEMPRE dejar ~30% de vóxeles como anomalía aunque la distribución de densidad sea ruido plano (std minúsculo). Esto fabrica anomalías y un best_target plausible incluso cuando la inversión no recuperó contraste físico real. El propio comentario admite que el objetivo es 'garantizar' anomalías, no detectarlas.
- fix: Anclar el cutoff a un contraste físico mínimo absoluto (p.ej. base_density + delta_min en t/m3) y reportar 'sin anomalías significativas' cuando std<umbral, en vez de re-escalar para producir un 30% artificial.
- VERIFICACION: incierto (sev->) :: verificacion fallo
### [P1] grav-fallback-04 | dim:3 (manejo de errores) / 8 (fallback silencioso) | conf:alta
**Cascada de ~10 bloques except Exception → log.warning(...non-fatal) que dejan diagnósticos en NaN/None sin marcar el resultado como degradado**
- file: terraquantum-backend/services/geophysics_service.py:2198-2199, 2240-2241, 2314-2315, 2456-2457, 2479-2480, 2535-2536, 2547-2548, 2687-2694, 2794-2795, 2819-2820, 3053-3054
- impacto: Si DOI, posterior, focusing, checkerboard QA, R01/R02/R03/R06, manifest, VTK o FAVORABILITY/priority_class fallan, el run sigue y devuelve status='done' con campos en NaN/None o ausentes. El consumidor no puede distinguir 'no calculado por costo' de 'reventó'. La favorability/priority_class (decisión de targeting) puede no existir y el flujo no lo señala como fallo.
- fix: Acumular las fallas en una lista report_payload['degraded_components'] y degradar confidence_level/model_reliability cuando un componente crítico (favorability, solver post-proc) falla; no devolver 'done' silencioso.
- VERIFICACION: incierto (sev->) :: verificacion fallo
### [P1] grav-prov-05 | dim:7 (provenance) / 8 (fingir resultado) / 1 (correctitud de flag) | conf:alta
**is_demo_grade=True hardcodeado en TODO vóxel/target/report incluso cuando expose_demo_grade=False y grade=None**
- file: terraquantum-backend/services/geophysics_service.py:930, 981, 1363, 1435, 884-885
- impacto: El flag de provenance miente: cuando expose_demo_grade=False (default industrial) la ley sale None pero is_demo_grade sigue True. Un consumidor que filtre por is_demo_grade no puede confiar en el flag. El warning de 'grade heuristic used' se emite siempre, incluso sin grade. Provenance inconsistente = riesgo de cumplimiento.
- fix: Derivar is_demo_grade del parámetro real (is_demo_grade = bool(expose_demo_grade)) y emitir el warning del grade solo cuando se pobló grade.
- VERIFICACION: incierto (sev->) :: verificacion fallo
### [P1] grav-repro-06 | dim:7 (reproducibilidad/provenance) | conf:alta
**Run Manifest 'immutable' registra params.lambda_mag (raw, puede ser 0) en vez del _lambda_mag realmente usado (auto-seleccionado)**
- file: terraquantum-backend/services/geophysics_service.py:2778, 2057-2090, 2954
- impacto: El manifiesto industrial (SHA-256, audit trail) afirma que la inversión usó lambda_mag=0.0 cuando realmente usó 1e-4 u otro valor auto-seleccionado. Re-ejecutar desde el manifiesto NO reproduce el resultado. Rompe el objetivo de reproducibilidad que el propio HITO 2 pretende garantizar. Mismo patrón en el manifiesto magnético (línea 1854 registra params.lambda_mag).
- fix: Registrar en el manifiesto el _lambda_mag efectivo (y lambda_scan_meta) además del solicitado; idem rng_seed (hoy siempre None) y alpha_spatial efectivo.
- VERIFICACION: incierto (sev->) :: verificacion fallo
### [P1] grav-phys-07 | dim:2 (física/matemática) / 8 (finge resultado) | conf:alta
**estimate_grade_from_geophysics fabrica 'ley' minera desde densidad + NIR/Fe satelitales + factor regional hardcodeado**
- file: terraquantum-backend/services/geophysics_service.py:741-773, 754-759, 761-767
- impacto: Combinación de coeficientes mágicos sin base petrofísica que produce una 'ley' [0,5] a partir de densidad gravimétrica e índices satelitales NIR/Fe. La gravimetría NO mide ley. Aunque está tras expose_demo_grade=False por default, sigue alimentando avg_grade/avg_density_proxy_index/anomaly_intensity y best_target cuando se activa, y el factor regional sesga el número por un string de región. No es física; es un número inventado con apariencia de medición.
- fix: Aislar el proxy como 'qualitative_interpretive_index' explícito, sin escala 0-5 que sugiere %ley, y nunca derivarlo de nir/fe (satélite) mezclado con densidad (subsuelo).
- VERIFICACION: incierto (sev->) :: verificacion fallo
### [P2] grav-robust-08 | dim:3 (robustez) / 2 (física) | conf:media
**Validación de señal solo rechaza g≈0 global; una señal con offset DC constante (todo igual a C≠0) pasa y produce inversión espuria**
- file: terraquantum-backend/services/geophysics_service.py:397-400, 454-455
- impacto: Un set de observaciones con valor constante no nulo (p.ej. todas = 100, un DC puro sin anomalía) supera la validación y se invierte, generando un modelo de densidad sin sustento (la gravimetría sin contraste espacial no tiene información). Solo se degrada un score cualitativo, no se aborta. Robustez insuficiente en path crítico.
- fix: Rechazar (o exigir acknowledge) cuando std(g_observed) o el rango dinámico esté por debajo de un umbral físico relativo, no solo cuando es ~0.
### [P2] grav-robust-09 | dim:3 (robustez) / 8 (fallback) | conf:media
**Regional-residual se aplica DESPUÉS del chequeo de g≈0 y puede dejar residual degenerado sin re-validar**
- file: terraquantum-backend/services/geophysics_service.py:397-415
- impacto: Si la sustracción regional polinómica deja un residual ~0 o con NaN (p.ej. ajuste perfecto o mal condicionado), no hay re-validación: el residual degenerado entra al solver y produce un modelo plano que se reporta como válido. El orden de validación-antes-de-transformar deja un hueco.
- fix: Re-ejecutar las validaciones de finitud y rango dinámico sobre g_observed después de separate_regional_residual.
### [P2] grav-contract-10 | dim:4 (contrato API) / 1 (correctitud) | conf:media
**build_geophysics_report default expose_demo_grade=True contradice el default del schema (False) y el caller; riesgo de emitir ley en rama vacía**
- file: terraquantum-backend/services/geophysics_service.py:1294, 2850, 1345-1375
- impacto: Contrato inconsistente: el default de la función expone ley demo, opuesto a la política industrial del schema. Es una trampa para futuros llamadores y para tests que no pasen el flag; pueden re-introducir ley inventada en el payload sin querer.
- fix: Cambiar el default de build_geophysics_report a expose_demo_grade=False para alinearlo con el schema y el modo industrial.
### [P2] grav-phys-11 | dim:9 (duplicado/divergente) / 2 (física) | conf:media
**Bounds y base_density 2.6/4.2 cableados como literales en múltiples lugares (no leídos de params), divergiendo del bound real del solver**
- file: terraquantum-backend/services/geophysics_service.py:499, 748, 817, 1396, 1485, 1487, 2975
- impacto: params.density_min/density_max son configurables (schema permite hasta 8.0 para magnetita), pero density_score, el checkerboard QA y el grade asumen [2.6, 4.2] fijos. Para un depósito con density_min!=2.6, density_score y el QA usan base errónea → scores y métricas de resolución calculadas contra una base que no es la del solver. Lógica de la misma constante física duplicada y potencialmente divergente.
- fix: Propagar params.density_min como base_density a build_fit_diagnostics, density_score y al checkerboard QA, en vez de literales 2.6/4.2.
### [P3] grav-robust-12 | dim:3 (robustez) / 1 (correctitud) | conf:media
**Validación de duplicados de observaciones es O(n) con set de tuplas float — coordenadas casi-iguales no se detectan, exactas sí (riesgo igualdad de floats)**
- file: terraquantum-backend/services/geophysics_service.py:211-219
- impacto: La detección de duplicados compara igualdad exacta de floats. Dos sensores en (100.0000001, ...) y (100.0, ...) pasan como distintos aunque sean efectivamente el mismo punto (mal condiciona el kernel). Y un duplicado exacto aborta toda la corrida en vez de deduplicar/avisar. Comportamiento frágil para datos reales con jitter de GPS.
- fix: Deduplicar con tolerancia espacial (redondeo a cm) y emitir warning + merge en vez de raise, o documentar que se exige unicidad exacta.
### [P3] grav-robust-13 | dim:3 (manejo de errores) | conf:media
**Heartbeat thread silencia toda excepción de update_run_status; un fallo persistente de estado se vuelve invisible**
- file: terraquantum-backend/services/geophysics_service.py:1541-1555, 1607-1612, 1914-1919
- impacto: Si update_run_status falla sistemáticamente (DB caída, permisos), el frontend nunca recibe progreso ni el error, y el run aparenta colgado o salta de 0 a 'done'. La excepción tragada impide diagnosticar la causa.
- fix: Loggear la excepción al menos una vez (rate-limited) en vez de pass total; distinguir fallo transitorio de persistente.
### [P3] grav-perf-14 | dim:6 (rendimiento) | conf:baja
**El kernel forward sparse se reconstruye varias veces sobre celdas activas para diagnósticos (R-01, R-06) en hot path de cada inversión**
- file: terraquantum-backend/services/geophysics_service.py:2159-2168, 2344-2349, 1998-2003
- impacto: En modelos grandes (hasta 200k vóxeles Core + padding) cada diagnóstico construye/recupera un kernel denso-disperso sobre todas las activas. Si la cache key difiere por flotantes, se recomputa el kernel completo dos o tres veces por corrida, multiplicando el costo del post-proceso. Para escala industrial esto morderá la latencia.
- fix: Construir el G_active una sola vez tras el solve y reusarlo para R-01, R-06 y g_modeled, en vez de tres llamadas separadas confiando en la cache.
### [P2] grav-fallback-15 | dim:8 (fallback) / 3 (robustez) | conf:media
**active_voxels fallback 'defensivo' usa todos los voxels (incluido aire) si no hay activos, calculando densities sobre None**
- file: terraquantum-backend/services/geophysics_service.py:1378-1388
- impacto: Si todos los vóxeles de anomalía resultan inactivos (density None), el fallback reasigna active_voxels=voxels y luego float(v['density']) sobre None lanza TypeError (no caught aquí) o, si density es np.nan, contamina min/avg/max_density con NaN reportados como bounds 'válidos'. El fallback finge un conjunto activo en vez de reportar 'sin anomalías activas'.
- fix: Si no hay vóxeles activos, retornar el report de la rama 'not voxels' (status con densidades en 0/None y disclaimer), no forzar el cálculo sobre celdas de aire.

## csv-import  (P0:2 P1:5 P2:5 P3:2) archivos:12
### [P0] csv-json-01 | dim:3 (Robustez) y 4 (Contratos API) | conf:alta
**El endpoint /preview NO sanitiza NaN/Inf: emite tokens NaN que rompen JSON.parse del frontend**
- file: terraquantum-backend/api/gravity_import_api.py:597-611 (return de preview) vs 1121 (_sanitize_nan en invert)
- impacto: Las estadisticas de gravedad (GravityStats.std/mean/p5/p95) o sampling (mean_spacing_m, point_density_per_km2) pueden quedar en NaN/Inf (p.ej. area degenerada, un solo valor, varianza 0). FastAPI serializa float('nan') como el token literal `NaN`, que NO es JSON valido. El proxy Next preview hace `await backendResponse.json()` y el navegador hace JSON.parse -> lanza 'Unexpected token N'. Esto es EXACTAMENTE el sintoma reportado: 'subo CSV y dice que no es JSON / no llega JSON valido' en la fase de preview.
- fix: Envolver el return de preview_gravity_csv en _sanitize_nan(...) igual que invert. Idealmente registrar un exception/response renderer global que use allow_nan=False o sanitice toda salida.
- VERIFICACION: incierto (sev->) :: verificacion fallo
### [P1] csv-json-02 | dim:3 (Robustez) y 4 (Contratos API) | conf:alta
**Proxy /preview hace await backendResponse.json() incondicional: enmascara cualquier respuesta no-JSON del backend**
- file: terraquantum-web/app/api/gravity-import/preview/route.ts:34
- impacto: El usuario ve 'Error interno del proxy' / 'no es JSON valido' sin la causa real. La ruta /invert SI maneja esto correctamente (parsea texto y captura JSON.parse, lineas 86-97), demostrando que preview quedo sin la misma proteccion. Contrato inconsistente entre las dos rutas.
- fix: Replicar el patron de invert/route.ts: leer texto crudo, intentar JSON.parse en try/catch y, si falla, devolver {detail, raw: text.slice(0,1000), backendStatus}.
- VERIFICACION: incierto (sev->) :: verificacion fallo
### [P0] csv-mag-01 | dim:1 (Correctitud) y 4 (Contratos) | conf:alta
**Magnetometria no se puede importar: el parser exige columna de gravedad y unidad de la familia mGal/m-s2; nT no existe**
- file: terraquantum-backend/services/gravity_import_service.py:30 (ALLOWED_UNITS), 45-61 (GRAVITY_COLUMN_PRIORITY), 280-281, 301-303, 378-379
- impacto: El foco del usuario pide rastrear subida de magnetometria de punta a punta: un CSV magnetico real (columna en nT, sin columna de gravedad) SIEMPRE termina en _build_error_result con 'Missing gravity column' o 'Unsupported unit: nT'. La via 'magnetic_only' es codigo muerto en la practica porque no hay forma de aportar el valor magnetico ni su unidad. El subsistema declara soportar magnetometria pero no la importa.
- fix: Anadir unidades magneticas (nT) y columnas magneticas (magnetic_nt/tmi) al parser, y bifurcar la validacion de unidad/columna cuando gravity_type=='magnetic_only' para no exigir gravedad.
- VERIFICACION: incierto (sev->) :: verificacion fallo
### [P1] csv-silent-01 | dim:8 (Fallbacks silenciosos) y 3 (Robustez) | conf:alta
**pandas.read_csv con on_bad_lines='skip' descarta filas malformadas en silencio (fallback que finge exito)**
- file: terraquantum-backend/services/gravity_import_service.py:260
- impacto: Filas con numero de columnas incorrecto (CSV corrupto, comas extra) se eliminan sin contarse ni advertirse. row_count se calcula sobre el df YA filtrado (linea 360), asi que rejected_rows y los warnings NUNCA reflejan las filas perdidas. Un CSV donde la mitad de las estaciones esta malformada puede importar 'ok' con menos datos de los que el usuario cree, produciendo un modelo degradado que parece valido. Pecado capital del proyecto.
- fix: Usar on_bad_lines='error' o un handler que cuente y reporte filas descartadas; sumar esas filas a rejected_rows y emitir warning explicito.
- VERIFICACION: incierto (sev->) :: verificacion fallo
### [P1] csv-silent-02 | dim:3 (Robustez) y 8 (Fallbacks) | conf:alta
**except Exception global colapsa cualquier fallo de parseo en un string generico, perdiendo el traceback**
- file: terraquantum-backend/services/gravity_import_service.py:678-680
- impacto: Cualquier excepcion no-ValueError dentro del bloque de ~420 lineas (errores de pandas, scipy cKDTree, numpy, transform_coordinates, compute_auto_grid, ValidationError de GravityObservation) se convierte en un unico 'File parsing error: <msg>' sin distinguir causa. Un bug de codigo (p.ej. KeyError por columna) se presenta al usuario como si el CSV estuviera mal. Dificulta enormemente diagnosticar el reporte 'no llega JSON valido' porque oculta dónde fallo realmente.
- fix: Capturar excepciones especificas; loggear traceback con _log.exception; diferenciar errores de datos (culpa del CSV) de errores internos (HTTP 500 honesto).
- VERIFICACION: incierto (sev->) :: verificacion fallo
### [P2] csv-enc-01 | dim:3 (Robustez) | conf:alta
**read_csv fija encoding='utf-8'; un CSV exportado por Excel (Latin-1/cp1252) revienta el import**
- file: terraquantum-backend/services/gravity_import_service.py:260
- impacto: Excel en es-CL exporta CSV en cp1252; cualquier acento o el simbolo µ (microGal) en encabezado/datos provoca UnicodeDecodeError, atrapado por el except global (678) y devuelto como 'File parsing error'. Caso comunisimo en mineria chilena. El usuario no entiende por que su CSV 'valido' falla.
- fix: Intentar utf-8-sig y caer a latin-1/cp1252; o detectar encoding. Como minimo utf-8-sig para manejar BOM.
### [P2] csv-mojibake-01 | dim:2 (Unidades) y 9 (Codigo corrupto) | conf:alta
**Comparacion de unidad con mojibake 'm/sÂ²' nunca coincide: conversion_applied mal calculado para m/s2**
- file: terraquantum-backend/services/gravity_import_service.py:519
- impacto: Si el CSV declara unidad 'm/s²' (que SI esta en ALLOWED_UNITS, linea 30), la comparacion en 519 no la reconoce como 'sin conversion', por lo que conversion_applied=True aunque convert_to_ms2 devolvio el valor sin tocar (no hubo conversion real). El flag de provenance/metadata queda incorrecto. Sintoma de corrupcion de encoding del propio fuente.
- fix: Usar `first_unit not in ("m/s2", "m/s²")` con el caracter correcto, o normalizar la unidad antes de comparar reutilizando _normalize_unit del csv_analysis_service.
### [P1] csv-axis-01 | dim:2 (Ejes x=Norte vs Este) y 8 (Fallbacks) | conf:media
**Inferencia de coordenadas acepta ejes lat/lon intercambiados como 'latlon' sin marcar la ambiguedad de eje**
- file: terraquantum-backend/services/csv_analysis_service.py:395-407
- impacto: Convencion interna documentada: x_m=este/lon, z_m=norte/lat (lineas 64-66 del import service). Si el CSV trae las columnas al reves (lat en x, lon en z) y ambos valen <90, x_lat_z_lon=True y se clasifica 'latlon high' igual, dejando el dataset con Norte y Este intercambiados sin ninguna advertencia. La inversion 3D queda espejada/rotada 90 grados pero se reporta como georef de alta confianza. El hard-reject de la linea 414-420 del import service solo dispara si abs>90/180, no para una mina con lat/lon ambos pequenos.
- fix: Cuando x_lat_z_lon sea el caso ganador (en vez de x_lon_z_lat), bajar confianza y emitir warning de posible inversion de ejes; o exigir que el resolver de columnas (que SI conoce los nombres lat/lon) sea la unica fuente de verdad y no la inferencia por rango.
- VERIFICACION: incierto (sev->) :: verificacion fallo
### [P2] csv-mag-02 | dim:1 (Correctitud) y 8 (Fallbacks) | conf:media
**Gate de varianza cero por defecto solo se exceptua para magnetic_only, pero magnetic_only no llega aqui; gravedad real plana se rechaza pero el flujo magnetico esta roto antes**
- file: terraquantum-backend/services/gravity_import_service.py:559-563, 615-618
- impacto: Inconsistencia: el codigo finge soportar magnetic_only en QC fisico, pero la entrada magnetica jamas llega por los gates previos (csv-mag-01). Codigo muerto/contradictorio que enmascara que la magnetometria no funciona end-to-end.
- fix: Resolver csv-mag-01 primero; luego validar que para magnetic_only se valide nT y columna magnetica, no g en mGal.
### [P3] csv-dup-01 | dim:1 (Correctitud) | conf:media
**Deduplicacion exacta cuenta duplicados como rejected_rows aunque la fila sea valida, distorsionando row_count vs valid_rows**
- file: terraquantum-backend/services/gravity_import_service.py:431-446, 540
- impacto: Un CSV con muchas estaciones a la misma (x,y) pero distinta g (re-ocupaciones legitimas en gravimetria) ve casi todas sus filas descartadas como duplicados exactos por coordenada, pudiendo caer bajo el umbral de 10 y rechazarse, sin que el usuario entienda que el criterio fue solo coordenada (ignora g/tiempo). Mensaje poco accionable.
- fix: Documentar/relajar: la dedup por coordenada deberia promediar o conservar la primera con warning claro, no rechazar masivamente; o incluir g en la clave si re-ocupaciones son validas.
### [P3] csv-grid-01 | dim:9 (Codigo muerto/duplicado) | conf:media
**_classify_georef_full: extent >100km en latlon retorna MEDIUM por dos ramas identicas (codigo duplicado, rama muerta)**
- file: terraquantum-backend/api/gravity_import_api.py:298-303
- impacto: Logica confusa: el resultado no cambia con has_anchor en el caso >100km, contradiciendo el resto de la funcion donde anchor sube a HIGH. Deuda tecnica que dificulta razonar sobre confianza georef en datasets regionales.
- fix: Colapsar a una sola rama o diferenciar realmente el confidence segun has_anchor.
### [P2] csv-readiness-01 | dim:8 (Fallbacks que fingen) y 2 (georef) | conf:media
**classify_from_csv_analysis trata anchor_lat/lon como suficiente para LOCAL_ANCHORED pero un punto central no georreferencia por estacion (fallback que sobre-promete)**
- file: terraquantum-backend/services/spatial_readiness_service.py:313-314, 382; builder 96-127
- impacto: Con solo declarar un lat/lon central (el campo lat/lon obligatorio del form /invert), un dataset en metros locales se promueve a LOCAL_ANCHORED_CENTER habilitando co-registro DEM y elevacion MASL por voxel, pese a que el propio rationale admite 'orientacion y escala real no verificadas'. El gate _enforce_spatial_readiness_gate NO bloquea nada (lineas 521-530, cuerpo vacio). Resultado: se calcula elevacion/DEM sobre una georef no verificada y se presenta como dato, enmascarando que la ubicacion real es desconocida.
- fix: No habilitar can_use_dem/can_compute_voxel_masl basandose solo en un punto central; requerir verificacion o degradar a contexto visual con flag explicito de baja confianza, y que el gate realmente restrinja outputs georreferenciados.
### [P1] csv-gate-01 | dim:8 (Fallbacks que fingen resultados) | conf:alta
**_enforce_spatial_readiness_gate es un no-op: documenta hard gate industrial pero no bloquea ningun nivel**
- file: terraquantum-backend/api/gravity_import_api.py:480-530
- impacto: Un CSV con NO_SPATIAL_DATA (can_run_3d_inversion=False en el schema, linea 25 del service) igualmente corre la inversion 3D porque el gate no aplica esa bandera. El sistema produce un modelo 'fisicamente valido en espacio relativo' que el usuario puede malinterpretar como georreferenciado. La firma de la funcion (docstring 'Hard gate industrial', 'Lanza HTTPException(422)') miente respecto al comportamiento real.
- fix: Hacer que el gate respete can_run_3d_inversion y requiera acknowledge_spatial_risk para niveles que lo exigen (required_acknowledgement no nulo); o actualizar la documentacion para no afirmar que es un hard gate.
- VERIFICACION: incierto (sev->) :: verificacion fallo
### [P2] csv-preview-status-01 | dim:4 (Contratos API) | conf:media
**preview no diferencia status='error': devuelve HTTP 200 con observaciones vacias, el frontend no sabe que fallo el import**
- file: terraquantum-backend/api/gravity_import_api.py:557-611
- impacto: Un CSV invalido (p.ej. 'Missing gravity column') retorna 200 con status:'error' embebido y observationsPreview:[]; el proxy lo pasa como ok y el UI debe inspeccionar el campo status/errors manualmente. Si el UI asume 200=exito, muestra preview vacio sin mensaje de error claro, otra variante de 'parece funcionar pero falla en la practica'.
- fix: Devolver status HTTP apropiado (400/422) cuando result.status!='ok', o documentar el contrato y asegurar que el frontend ramifique por el campo status.

## block-model-export  (P0:0 P1:4 P2:6 P3:2) archivos:4
### [P1] bm-ubc-mod-order-01 | dim:2 (física/convención) + 9 (duplicado divergente) | conf:alta
**Bundle FASE 11: el .mod UBC se escribe en orden de vóxel equivocado (ix-fast) y sin flip Z, scrambleando el modelo respecto al .msh**
- file: terraquantum-backend/services/export_service.py:708-712 (_ubc_mod_text) y 846 (create_run_bundle_zip)
- impacto: El bundle industrial (botón de export que descarga model.msh+model.mod) entrega un modelo UBC-GIF/SimPEG con las celdas espacialmente permutadas y el eje Z invertido respecto a la malla. Cualquier importación a UBC-GIF Grav3D o SimPEG produce un cuerpo de densidad ubicado en el lugar equivocado — exactamente lo opuesto a 'industrial'. Dos rutas de export del mismo formato divergen.
- fix: Eliminar _ubc_mod_text/_ubc_msh_text inline y reusar export_block_model_to_ubc (o replicar su reorder 'for ix: for iy: for iz' + flip Z). Idealmente create_run_bundle_zip debería leer los .msh/.mod ya generados en disco por el pipeline canónico en vez de regenerarlos con lógica distinta.
- VERIFICACION: incierto (sev->) :: verificacion fallo
### [P2] bm-ubc-msh-origin-02 | dim:2 (convención de signo/origen) + 9 (duplicado divergente) | conf:alta
**Bundle FASE 11: _ubc_msh_text fija origen 0 0 0 sin convención Z-arriba, inconsistente con el exportador canónico**
- file: terraquantum-backend/services/export_service.py:701-705
- impacto: El .msh del bundle declara un origen incompatible con el .mod (que además está en orden equivocado), agravando el desalineamiento. Un usuario que georreferencie por el origen del .msh obtiene posiciones absolutas erróneas.
- fix: Usar la misma convención de origen NW-superior y Z-arriba que el exportador canónico, o reusar el archivo .msh ya escrito en disco.
### [P1] bm-read-parquet-nonjson-03 | dim:3 (robustez / respuesta no-JSON) | conf:alta
**build_block_model_response: pl.read_parquet sin try/except — un parquet corrupto produce 500 no-JSON**
- file: terraquantum-backend/services/block_model_service.py:556 (df = pl.read_parquet(str(parquet_path))) y 640 (anomaly_df)
- impacto: Si el parquet existe pero está corrupto, truncado, o con schema ilegible (escritura interrumpida, disco lleno a mitad de write_parquet), polars lanza excepción no capturada → FastAPI devuelve 500 con traceback HTML. Este es exactamente el síntoma 'no llega JSON válido' que el frontend no sabe parsear. count_parquet_rows_or_none (316-324) SÍ envuelve en try/except, demostrando que el patrón seguro existe pero no se aplicó al read principal.
- fix: Envolver el read principal y el del anomaly en try/except que retorne empty_block_model_response con un error string descriptivo (JSON válido), igual que el resto de ramas de error.
- VERIFICACION: incierto (sev->) :: verificacion fallo
### [P1] bm-density-default-26-04 | dim:8 (fallback silencioso que finge resultados) | conf:alta
**ensure_visual_columns inventa density=2.6 cuando no hay densidad — fallback silencioso que finge resultado físico**
- file: terraquantum-backend/services/block_model_service.py:79-80
- impacto: Un block model sin columna de densidad (esquema roto, run fallido, parquet de otra física) se sirve como si todas las celdas tuvieran densidad de roca encajante 2.6. visual_score colapsa a 0 (rango degenerado), isDegenerate=True, pero el endpoint devuelve 200 con 'cells' plausibles. El usuario ve un bloque uniforme en lugar de un error honesto. _densities_from_parquet (líneas 687, 698) repite el mismo pecado: 'return [2.6] * total' cuando el parquet no existe o falla, llenando el bundle exportado de 2.6 falsos.
- fix: Si falta toda fuente de densidad, fallar honestamente (error en la respuesta) o marcar explícitamente has_density_data=False y NO emitir cells con densidad fabricada. En _densities_from_parquet retornar NaN (no 2.6) y propagar el faltante al manifiesto.
- VERIFICACION: incierto (sev->) :: verificacion fallo
### [P2] bm-economic-visualscore-missing-05 | dim:4 (contrato API frontend/backend) | conf:media
**Contrato roto: en modo economic el JSON omite cell.visual_score, pero el worker/Arrow asumen su presencia**
- file: terraquantum-backend/services/block_model_service.py:730-734
- impacto: El payload economic (JSON) y el payload Arrow exponen campos distintos para la misma celda según la ruta. En economic+JSON el worker cae al fallback densityRatio sin avisar; el coloreo difiere entre transporte Arrow y JSON para el mismo modo. Inconsistencia de contrato que produce visuales distintas según qué ruta gane el race Arrow/JSON.
- fix: Unificar el set de campos por celda entre la ruta JSON y la Arrow; incluir visual_score también en economic (o documentar el fallback explícitamente en ambos lados).
### [P1] bm-qa-fake-pearson-06 | dim:8 (fallback silencioso que finge resultados) | conf:alta
**get_run_qa_diagnostics fabrica un pearson_r y una L-curve plausibles cuando no existen datos reales**
- file: terraquantum-backend/services/export_service.py:888-918
- impacto: El DiagnosticPanel recibe un checkerboard Pearson r de 0.82/0.64/0.38 y una L-curve que PARECEN un test QA real, derivados sólo del fit_level. Aunque se setea is_real=False y se añade ' (estimado)' al status, el número numérico (round(r_val,4)) y los puntos de la L-curve son indistinguibles de un resultado medido para cualquier consumidor que lea pearson_r/points y no el flag. Riesgo de presentar QA inventado como industrial.
- fix: Cuando no hay test real, devolver pearson_r=None y points=[] (no valores fabricados). La UI debe mostrar 'no ejecutado', no un número plausible.
- VERIFICACION: incierto (sev->) :: verificacion fallo
### [P2] bm-densities-grid-mismatch-07 | dim:1 (correctitud) + 7 (reproducibilidad) | conf:media
**create_run_bundle_zip toma nx/ny/nz de inputs.json y trunca/padea densidades del parquet sin verificar que coincidan**
- file: terraquantum-backend/services/export_service.py:837-848 y 681-698
- impacto: Si inputs.json nx*ny*nz != filas del parquet (p.ej. auto-params/scale-aware reescribió la malla después de escribir inputs, o un run legacy), el bundle trunca o rellena con NaN sin avisar, desalineando densidades vs coordenadas. Aunque hoy coincidan (verificado 43x15x42=27090), no hay validación que lo garantice — es una bomba de tiempo silenciosa.
- fix: Leer nx/ny/nz desde el run_manifest (grid efectivo) o validar len(parquet)==nx*ny*nz y abortar/avisar si difiere, en vez de pad/truncar en silencio.
### [P2] bm-deep-sanitize-bigpayload-08 | dim:6 (rendimiento/escalabilidad) | conf:media
**Ruta JSON recorre cada celda con iter_rows + deep_sanitize_nan recursivo: O(n) dicts Python sobre payloads grandes**
- file: terraquantum-backend/services/block_model_service.py:674-736 y 777 (deep_sanitize_nan(response))
- impacto: En modo 'full' con bloques regionales (verificado: runs Bushveld) el endpoint JSON construye y sanitiza 200k+ dicts en cada request — latencia alta y picos de memoria. La ruta Arrow existe justamente para evitar esto, pero el JSON sigue siendo el fallback y no impone un límite duro en full.
- fix: Imponer límite de celdas también en modo full para la ruta JSON, o deprecar JSON para full y forzar Arrow. Evitar la doble pasada deep_sanitize_nan (ya se sanitiza por-celda con sanitize_nan_value).
### [P2] bm-resolve-silent-legacy-09 | dim:8 (fallback silencioso) + 1 (correctitud) | conf:media
**resolve_block_model_reference cae a un path inexistente (legacy) sin error cuando no se da project/run y nada existe**
- file: terraquantum-backend/core/block_model_store.py:534-538
- impacto: build_block_model_response luego hace 'if not parquet_path.exists(): return empty_block_model_response(...)' así que degrada a respuesta vacía (no crash), pero la referencia legacy silenciosa contradice la política 'No existe fallback silencioso a modelo legacy' que SÍ se aplica en resolve_mine_design_block_model_reference (líneas 756-765). Las dos funciones hermanas tienen políticas opuestas: una bloquea el legacy, la otra lo permite.
- fix: Unificar política: si no hay project/run y no existe ningún candidato real, lanzar ValueError como hace resolve_mine_design_block_model_reference, en lugar de devolver un path fantasma.
### [P2] bm-schema-version-soft-10 | dim:7 (reproducibilidad/versionado) + 8 (fallback silencioso) | conf:media
**validate_parquet_schema sólo se loguea como warning al escribir el parquet gravity; un schema inválido no bloquea nada**
- file: terraquantum-backend/core/block_model_store.py:659-713 (validador) ; geophysics_service.py:2738-2744 (consumo)
- impacto: Un parquet que viola el contrato v3.0 (falta x/y/z/density, schema_version distinto) se escribe igual y se sirve igual; el 'contrato' es decorativo. Además validate_parquet_schema sólo lee n_rows=1, así que columnas presentes pero con todos los valores null en filas posteriores pasarían como válidas.
- fix: Decidir si el schema es contractual: si lo es, abortar/marcar el run como inválido cuando valid=False, no sólo loguear. Documentar que la validación es de presencia de columnas, no de contenido.
### [P3] bm-report-inputs-attr-11 | dim:3 (robustez) | conf:baja
**generate_technical_report_html usa inputs.get(...) tras _read_required_json sin garantizar dict cuando se inyecta por kwarg**
- file: terraquantum-backend/reporting/report_generator.py:172-173, 517-518
- impacto: Genera HTML del reporte; un inputs inyectado no-dict (tests o caller interno) rompe con 500/excepción en vez de error claro. report sí pasa por _read_required_json sólo cuando es None; igual gap.
- fix: Normalizar inputs/report con _as_dict() tras la inyección, o validar isinstance(dict) en ambas ramas.
### [P3] bm-arrow-bounds-rawvscentered-12 | dim:1 (correctitud) + 4 (contrato) | conf:media
**Arrow: coords se centran (x-x_c) pero los headers X-TQ-Bounds usan x_min/x_max RAW sin centrar — bounds no describen las coords servidas**
- file: terraquantum-backend/services/block_model_service.py:868-872 y 928-929
- impacto: Un consumidor que use los headers de bounds para dimensionar/posicionar la escena obtiene un rango en coordenadas absolutas, mientras las coords de las celdas vienen centradas y con Y invertida. El frontend de hecho ignora los headers y recalcula bounds de los TypedArrays (frontendApi.ts:1196-1206), pero el header es engañoso para cualquier otro consumidor del contrato Arrow.
- fix: Emitir los bounds en el mismo sistema que las coords servidas (centrado + Y invertida), o documentar explícitamente que los bounds son coords mundo absolutas pre-transform.

## spatial-georef  (P0:1 P1:3 P2:4 P3:4) archivos:9
### [P0] georef-axis-convention-conflict | dim:2 (Física/Matemática: ejes intercambiados x=Norte vs Este) | conf:media
**Conflicto de convención de ejes: el motor físico usa x=Norte/z=Este, pero la georreferenciación y muestreo DEM usan x=Este/z=Norte → lat/lon y elevación transpuestas**
- file: terraquantum-backend/services/elevation_enrichment_service.py:258-259, 247-249
- impacto: El block_model.parquet hereda los ejes x_m/z_m de la malla de inversión, cuyo convenio físico es x=Norte, z=Este. Pero el servicio de elevación trata x como Easting y z como Northing. Resultado: para cualquier proyecto donde el CSV/física tenga geometría no cuadrada o anisotrópica, el lat/lon reconstruido y la elevación muestreada del DEM quedan TRANSPUESTOS (intercambiados N↔E). Un voxel en el extremo Norte recibe la elevación del extremo Este y una coordenada geográfica equivocada. La georef parece válida (no falla) pero es físicamente incorrecta — el síntoma 'no toma en cuenta el mapa de Google Earth' es consistente con esto.
- fix: Definir UN único convenio de ejes para todo el backend y documentarlo en un solo lugar. Si el convenio canónico es x=Norte/z=Este (como afirma la física), entonces en elevation_enrichment_service.py el easting debe derivarse de z_f y el northing de x_f (intercambiar), y geo_utils.sample_dem_elevation debe mapear z_m→columna(Este)/x_m→fila(Norte). Alternativamente, alinear coordinate_transform_service para que x_min_raw sea Northing. Agregar un test de extremo (voxel esquina NE conocido) que verifique lat/lon contra valor pyproj esperado.
- VERIFICACION: incierto (sev->) :: verificacion fallo
### [P1] georef-mock-dem-fake-zero | dim:8 (Fallbacks silenciosos que fingen resultados) | conf:alta
**DEM mock todo-ceros devuelve elevación 0.0 m s.n.m. como dato válido (fallback silencioso que finge resultado)**
- file: terraquantum-backend/core/geo_utils.py:271-273
- impacto: Cuando GEE no está inicializado (sin credenciales, paquete ausente, o área oceánica) el DEM es todo ceros. enrich_block_model_with_elevation entonces escribe surface_elevation_masl=0.0 y voxel_elevation_masl = -depth para TODOS los voxels, y has_elevation_data=True. El consumidor recibe elevaciones absolutas de 0 m s.n.m. plausibles pero ficticias; un proyecto a 4000 m de altura aparece a nivel del mar. El warning 'DEM mock' va a la columna spatial_reference_warning por fila pero el status del enrich sigue 'ok'.
- fix: Cuando el DEM es mock (todo ceros) NO emitir surface_elevation_masl=0.0; devolver None y marcar georef_confidence/dem_source como conceptual de forma que el status del enrich refleje 'degraded' y has_elevation_data=False. O propagar dem_source='mock_v1_gee_fallback' a una bandera dura que el frontend muestre como CONCEPTUAL, no como masl real.
- VERIFICACION: incierto (sev->) :: verificacion fallo
### [P1] georef-gee-silent-unavailable | dim:3/8 (Robustez + fallback silencioso) | conf:alta
**GEE falla en silencio (is_available()=False) y el sistema entero cae a DEM mock sin error al usuario**
- file: terraquantum-backend/core/gee_client.py:16-49, 52-54
- impacto: El usuario que dice 'no toma en cuenta el mapa de Google Earth' probablemente tiene GEE no inicializado (credenciales ausentes o paquete ee no instalado). Todo el pipeline de DEM/textura/spectral degrada a mock/'not_evaluated' SIN un error visible en la respuesta principal — solo un _log.warning interno. No hay forma de distinguir 'georef real' de 'georef inventada' desde la respuesta de get_terrain_data salvo inspeccionar source='mock_v1...' string.
- fix: Exponer un estado explícito gee_available en TerrainResponse/metadata y propagarlo como campo booleano de primer nivel. Hacer que el frontend muestre un banner cuando source contiene 'mock'. Considerar un modo estricto donde la ausencia de GEE en un proyecto georreferenciado HIGH/MEDIUM sea un error duro en vez de degradación silenciosa.
- VERIFICACION: incierto (sev->) :: verificacion fallo
### [P1] georef-dem-symmetric-offset-assumption | dim:1/2 (Correctitud + geometría espacial) | conf:media
**sample_dem_elevation asume DEM centrado simétricamente sobre el modelo, pero el bbox real puede ser asimétrico (footprint corners + margen)**
- file: terraquantum-backend/core/geo_utils.py:283-292
- impacto: Si el footprint real no está geométricamente centrado respecto a la malla de inversión (caso común cuando el centro lat/lon del proyecto no coincide con el centroide de las estaciones), el offset simétrico asignará a cada voxel la elevación de una posición DEM desplazada. El error de co-registro puede ser de cientos de metros horizontales, asignando elevaciones del cerro vecino. No hay validación de que la suposición de centrado se cumpla.
- fix: Calcular el offset real usando el origen UTM del modelo (x_min_raw/z_min_raw) y las esquinas reales del bbox en metros, en lugar de asumir centrado simétrico. Mapear cada voxel a su lat/lon real (ya se calcula en elevation_enrichment_service.py:258-265) y muestrear el DEM por lat/lon, no por offset relativo.
- VERIFICACION: incierto (sev->) :: verificacion fallo
### [P2] georef-axis-bbox-cellsize-swap | dim:2 (consistencia de ejes en metadata) | conf:media
**cell_size_x_m se calcula desde el rango de LONGITUD y cell_size_z_m desde LATITUD, mezclando con la convención física x=Norte**
- file: terraquantum-backend/services/satellite_service.py:655-660
- impacto: La metadata cell_size_x/z y el mapeo fila/columna del DEM quedan atados al convenio Este/Norte del terreno. Combinado con el hallazgo georef-axis-convention-conflict, propaga la transposición a las dimensiones de celda reportadas. Si el array de sampleRectangle no es estrictamente norte-arriba tras el zoom bilineal, la inversión de fila (línea 292) podría además voltear la elevación N-S.
- fix: Unificar convenio de ejes (ver georef-axis-convention-conflict) y añadir un test que verifique la orientación del array de GEE (p.ej. muestrear un punto de elevación conocida en una esquina). Documentar explícitamente que sampleRectangle devuelve fila0=max_lat.
### [P2] georef-latlon-blocked-for-low-confidence | dim:8/3 (degradación que oculta capacidad real) | conf:alta
**lat/lon por voxel se bloquea para georef LOW aun cuando existe origen UTM válido, dejando coordenadas null silenciosamente**
- file: terraquantum-backend/services/elevation_enrichment_service.py:189-194, 199-200
- impacto: Un proyecto con UTM declarado pero confianza LOW (p.ej. CRS inferido) que SÍ podría producir lat/lon geodésicos correctos vía pyproj queda con lat/lon=null. El frontend no puede ubicar los voxels en el mapa. La decisión de bloquear es de política, no técnica; el usuario percibe 'no se georreferencia' cuando los datos existen.
- fix: Permitir lat/lon para LOW con un flag de confianza explícito (lat/lon calculados pero marcados georef_confidence=LOW), en vez de null absoluto. Distinguir 'no calculable' (sin EPSG/origen) de 'calculable pero baja confianza'.
### [P2] georef-epsg-int-coercion-drops-valid | dim:3/4 (robustez + contrato) | conf:alta
**Coerción de epsg_code/utm_zone descarta valores válidos por chequeo de tipo estricto (int aceptado, float/str numérico descartado)**
- file: terraquantum-backend/services/elevation_enrichment_service.py:79-80, 174-179
- impacto: Un gravity_import_metadata.json que serializó epsg_code como número con decimal, o un project_meta con epsg como string, hace que can_latlon (línea 189-194) sea False → lat/lon null aunque el CRS esté bien definido. Falla silenciosa de georef por un detalle de tipado JSON.
- fix: Coercionar de forma tolerante: aceptar int, float entero y string numérico para epsg_code (int(float(x))), y normalizar utm_zone a str. Reusar _safe_int/_safe_float ya existentes en spectral_service.
### [P2] georef-extent-vs-bbox-mismatch | dim:1 (Correctitud de flujo de datos) | conf:media
**extent_x_m/extent_z_m persistidos pueden no corresponder al bbox usado para muestrear el DEM (footprint vs metadata vs center), rompiendo el offset del DEM**
- file: terraquantum-backend/services/satellite_service.py:586-608, 686-687
- impacto: Si extent (model_extent) viene de una fuente y bbox de otra, offset_x/z queda mal calculado y el muestreo DEM se desplaza. Por ejemplo bbox desde footprint corners pero extent desde CSV: el offset asume relación que no existe. Co-registro DEM↔modelo incorrecto sin aviso.
- fix: Garantizar que extent_x_m/extent_z_m persistidos sean SIEMPRE los del mismo origen que el bbox (derivar uno del otro). Idealmente eliminar la suposición de offset y muestrear por lat/lon real del voxel.
### [P3] georef-spectral-iron-clay-zero-denominator-clamp | dim:2/8 (física proxy + fallback que finge resultado) | conf:baja
**Proxies espectrales usan denominador con .max(1) que distorsiona el ratio en zonas de baja reflectancia y produce scores plausibles desde datos degenerados**
- file: terraquantum-backend/services/spectral_service.py:290-295
- impacto: El cálculo del ratio B4/B2 asume valores en una escala donde 1 es un piso razonable, pero S2_SR_HARMONIZED entrega DN escalados (~0-10000) o reflectancia 0-1 según harmonización. El .max(1) protege contra div/0 pero no normaliza la escala, por lo que iron_oxide_proxy y su normalized_score pueden quedar saturados o nulos sin reflejar geología. Es proxy exploratorio (hay disclaimers fuertes, líneas 45-49) así que severidad baja, pero el surface_support_score derivado puede ser engañoso.
- fix: Verificar la escala real de las bandas S2_SR_HARMONIZED y usar un denominador/normalización consistente (p.ej. trabajar en reflectancia 0-1 dividiendo por 10000 antes del ratio). Calibrar los umbrales de _score_iron/_score_clay a la escala correcta.
### [P3] georef-dem-residual-nan-mean-fill | dim:8 (fallback que finge dato) | conf:media
**NaN residuales del DEM se rellenan con la media regional, fabricando topografía plana donde no hay dato**
- file: terraquantum-backend/services/satellite_service.py:489-497
- impacto: Pixeles sin dato real (huecos costeros, sombras de radar) reciben la elevación media de la región. Si un voxel del modelo cae sobre uno de esos pixeles, su surface_elevation_masl es inventado (la media) y se reporta como dato válido sin distinción. Para regiones con buenos datos GLO30 es raro, de ahí severidad baja.
- fix: Registrar la fracción de pixeles rellenados en terrain_metadata y, si supera un umbral, degradar georef_confidence o marcar spatial_reference_warning en los voxels afectados.
### [P3] georef-duplicated-extent-logic | dim:9 (Código duplicado que diverge) | conf:alta
**Lógica de derivación de extent desde CSV duplicada en tres archivos con divergencia de tags de fuente**
- file: terraquantum-backend/services/spectral_service.py:178-236
- impacto: Tres implementaciones de 'leer extent del CSV' que pueden divergir: si cambia el nombre de archivo o la convención de columnas, spectral_service usa un literal hardcodeado y se desincroniza. Mantenibilidad/consistencia, sin impacto físico inmediato.
- fix: Unificar en una única función (p.ej. geo_utils._derive_extent_from_csv) y consumirla desde satellite_service y spectral_service, normalizando los tags de fuente.
### [P3] georef-bilinear-clamp-edge-flattening | dim:1 (correctitud numérica menor) | conf:media
**_bilinear_interp colapsa a vecino único en bordes por el clamp de índice, perdiendo interpolación en la franja exterior del DEM**
- file: terraquantum-backend/core/geo_utils.py:192-201
- impacto: En el borde exacto del DEM la interpolación puede extrapolar levemente (dr ligeramente >1) o aplanarse. Efecto pequeño (decenas de cm a metros), de ahí P3, pero afecta voxels en el perímetro del modelo que es justo donde el co-registro ya es más débil.
- fix: Tras clampear row_f/col_f a [0, n-1], clampear también dr/dc a [0,1] explícitamente antes de mezclar, para garantizar interpolación pura sin extrapolación en bordes.

## economics-mine  (P0:2 P1:5 P2:8 P3:2) archivos:10
### [P0] econ-grade-tonnage-zero-01 | dim:8 (fallbacks silenciosos que fingen resultados) | conf:alta
**El parquet real de inversión no tiene columnas grade/tonnage/domain → toda la economía se calcula sobre CEROS y devuelve 'done'**
- file: terraquantum-backend\services\block_model_service.py:100-107
- impacto: El export de la inversión (gravimetry.py:1765-1780) escribe density, density_contrast, bulk_rock_mass_kg, relative_target_score, exploration_index, posterior_std — pero NUNCA grade, tonnage ni domain. Al cargar ese parquet en generate_pit_design (pit_design_service.py:300-320), ensure_visual_columns rellena grade=0.0, tonnage=0.0, domain=0. Entonces ingresos = tonnage*(grade/100)*recovery*price = 0, costos = tonnage*coste = 0, profit = 0 en TODOS los bloques. El LG engine recibe profit=0 (engine.py:106-109: add_tedge(node,0,0)), no mina nada o mina degeneradamente; NPV≈0, tonnage=0, avg_grade=0, strip_ratio=None. El endpoint igualmente retorna status='done' con métricas plausibles-pero-vacías en vez de fallar. Es el pecado capital: un pit económico 'válido' construido sobre datos inexistentes.
- fix: En generate_pit_design, validar explícitamente que el parquet tenga grade y tonnage NO-default (o un mapeo declarado desde bulk_rock_mass_kg/density). Si grade==0 en todo el modelo o tonnage es la columna default, abortar con HTTP 422 'block model sin ley/tonelaje: no se puede correr economía'. Eliminar los fill silenciosos a 0.0 en ensure_visual_columns para el path de pit-design.
- VERIFICACION: incierto (sev->) :: verificacion fallo
### [P0] econ-grade-proxy-02 | dim:8 (fallback que finge resultado) / 2 (física) | conf:alta
**Aun cuando hay 'grade', es un PROXY heurístico derivado de densidad — no una ley geoquímica; la economía lo trata como Cu% real**
- file: terraquantum-backend\generate_deposit.py:166-171
- impacto: La única fuente de 'grade' es generate_deposit (datos sintéticos) donde grade es una transformación lineal inventada de la densidad invertida. report_generator.py:37 lo admite: 'Ley estimada (grade): PROXY HEURÍSTICO derivado del contraste de densidad'. Sin embargo pit_design_service:377 lo usa como ley metalúrgica real (ingresos = tonnage*(grade/100)*recovery*price) y reporta NPV/cutoff como si fueran defendibles. Un software industrial (Leapfrog/Geosoft) jamás derivaría Cu% de densidad gravimétrica: no hay relación física unívoca densidad→ley. El NPV resultante es ficción cuantitativa.
- fix: Marcar todo NPV/tonelaje/ley como 'proxy no validado' en la RESPUESTA de la API (no solo en el PDF), o exigir una columna grade proveniente de ensayos/sondajes reales. No emitir cutoff_grade ni NPV en USD sin ley real.
- VERIFICACION: incierto (sev->) :: verificacion fallo
### [P1] econ-cutoff-units-03 | dim:2 (unidades) / 1 (correctitud) | conf:alta
**cutoff_grade calculado sin el factor /100 → inconsistente con la fórmula de ingresos (off by 100x)**
- file: terraquantum-backend\services\pit_design_service.py:545
- impacto: La fórmula de ingresos trata grade como porcentaje (divide por 100). El break-even real es grade_cutoff = 100 * processing_cost / (recovery*price). Pero cutoff_grade omite el ×100, por lo que devuelve un valor 100 veces menor que el cutoff coherente con la propia función de ingresos. Cualquier comparación grade>cutoff (o lectura del usuario) está mal escalada por 100. Unidades inconsistentes dentro del mismo servicio.
- fix: cutoff_grade = 100.0 * req.processing_cost / (req.recovery * req.price), o eliminar el /100 de ingresos y unificar la convención de unidades de 'grade' (fracción vs porcentaje) en todo el servicio.
- VERIFICACION: incierto (sev->) :: verificacion fallo
### [P1] econ-bench-blocksize-axis-04 | dim:2 (ejes/unidades) / 1 (correctitud) | conf:media
**Profundidad del pit usa block_size_x para convertir índices de profundidad (eje iy) a metros → escala vertical incorrecta si block_size_y != block_size_x**
- file: terraquantum-backend\pit_mesh.py:254-270
- impacto: build_excavation_surface devuelve 'deepest' contado en índices del eje iy (profundidad). pit_design_service.py:417 y :425 pasan req.block_size_x como 'block_size' a quantize_surface_to_benches y build_benched_mesh. La conversión depth->metros (y_bot = -depth*block_size_x) y el bench_blocks (bench_height/block_size_x) usan el tamaño horizontal X para un eje vertical. Si block_size_y difiere de block_size_x (el schema los permite independientes: 10/10/10 default pero configurables), la geometría del rajo y la altura de bancos quedan mal escaladas. Convención de eje/tamaño cruzada.
- fix: Pasar block_size_y para todas las conversiones que involucran el eje de profundidad (iy) en build_excavation_surface/quantize/build_benched_mesh, o documentar y forzar block_size_x==block_size_y==block_size_z.
- VERIFICACION: incierto (sev->) :: verificacion fallo
### [P1] econ-lg-profit-rescale-05 | dim:7 (reproducibilidad) / 1 (correctitud) | conf:media
**Re-escalado del profit para el motor LG cambia la magnitud absoluta pero el scheduler usa profit_final sin re-escalar → NPV mezcla dos escalas**
- file: terraquantum-backend\services\pit_design_service.py:392-440
- impacto: El profit pasado al LG (selección de bloques) se normaliza dividiendo por un factor dependiente de _profit_max_abs del dataset. Esa normalización solo se aplica a la selección, no al profit_final que alimenta al scheduler (NPV). Aunque la intención es preservar orden relativo, el factor de normalización no es determinista entre datasets (depende del max del modelo), y además final_costos queda con el valor de la ÚLTIMA iteración del loop de revenue_factors (rf=1.0), no del factor por fase — ver hallazgo 06. El resultado: la envolvente seleccionada y el NPV usan supuestos de precio distintos.
- fix: Re-escalar solo dentro del engine y devolver una bandera de escala; calcular NPV con el mismo profit (precio) que definió la envolvente. Documentar y fijar el factor de normalización.
- VERIFICACION: incierto (sev->) :: verificacion fallo
### [P2] econ-final-costos-overwrite-06 | dim:1 (correctitud) / 9 (lógica confusa) | conf:media
**final_costos se sobrescribe en cada iteración del loop de fases; profit_final usa solo los costos de la última fase**
- file: terraquantum-backend\services\pit_design_service.py:379-440
- impacto: final_costos = costos dentro del loop simplemente guarda el costo de la última iteración (idx=2). Como 'costos' no depende de rf, el valor es el mismo en las 3 iteraciones, así que el resultado es correcto por coincidencia. Pero el patrón 'final_costos = costos' dentro del loop es código frágil/confuso: si alguien hace que costos dependa de rf (descuentos por fase, costos incrementales), el NPV quedaría silenciosamente con la última fase. profit_final correcto solo por accidente.
- fix: Calcular costos una sola vez fuera del loop (no dependen de rf) y nombrar la variable explícitamente. Eliminar la asignación dentro del loop.
### [P1] econ-tonnage-normalize-fake-07 | dim:8 (fallback que finge) / 2 (unidades) | conf:alta
**El scheduler reemplaza el tonelaje real por uno 'normalizado a 25m' cuando es >1e8 t/bloque → NPV se reporta en USD absolutos sobre tonelaje ficticio**
- file: terraquantum-backend\scheduler.py:156-166
- impacto: En escala regional el tonelaje por bloque real se descarta y se sustituye por density*15625 (bloque ficticio de 25m). El propio comentario admite 'NO representativo'. Pero profit (prof[]) NO se re-escala con el mismo factor, así que el cash flow por bloque (cf_y += p) se acumula con el profit calculado del tonelaje REAL mientras las restricciones de capacidad (m_rem>=t, p_rem>=t) usan el tonelaje FICTICIO. El NPV final en $ mezcla profit de escala real con secuenciamiento de escala 25m → NPV numérico sin significado físico, pero reportado como 'NPV: $X' defendible.
- fix: Si se normaliza el tonelaje, normalizar consistentemente profit y capacidades, y degradar el NPV a 'relativo/no-monetario' en la respuesta. No reportar $ absolutos sobre tonelaje admitidamente ficticio.
- VERIFICACION: incierto (sev->) :: verificacion fallo
### [P1] econ-domain-default-waste-08 | dim:8 (fallback silencioso) / 1 (correctitud) | conf:alta
**domain default=0 hace que TODO sea estéril: processing_cost nunca se aplica y strip_ratio=None silenciosamente**
- file: terraquantum-backend\services\pit_design_service.py:379-528
- impacto: El parquet de inversión no trae 'domain' (gravimetry.py no lo exporta) → ensure_visual_columns lo pone en 0. Con domain==0: (domain>0) es False en todos lados → el processing_cost NUNCA se suma a los costos (ingresos inflados artificialmente), y ore_mask queda vacío → ore_tonnage=0 → strip_ratio=None. Es decir, el modelo trata todo como estéril metalúrgicamente pero igual cobra ingresos por la 'ley' del bloque. Resultado económico internamente contradictorio, sin aviso.
- fix: Exigir columna domain real (clasificación ore/waste). Si ausente, no asumir 0; abortar o derivar domain de un cutoff explícito sobre la ley. Avisar cuando processing_cost queda inerte.
- VERIFICACION: incierto (sev->) :: verificacion fallo
### [P2] econ-density-default-26-09 | dim:8 (fallback silencioso) | conf:alta
**density default=2.6 enmascara modelos sin densidad y propaga a tonnage/grade proxy**
- file: terraquantum-backend\services\block_model_service.py:79-80
- impacto: Si el parquet no tiene density/rho/density_t_m3, se inyecta 2.6 t/m3 uniforme. Como tonnage y el grade-proxy derivan de density, un modelo sin densidad real produciría tonelaje y ley constantes plausibles en vez de fallar. Mismo patrón de fallback que finge datos. Además 2.6 es el mismo valor de fondo usado como density_contrast baseline (gravimetry density-2.6), creando contrast=0 → favorabilidad degenerada.
- fix: No inyectar 2.6; si density ausente, error explícito. La densidad es input físico primario, no debe defaultearse.
### [P2] favor-msx-jaccard-zero-10 | dim:2 (física) / 3 (robustez) | conf:media
**Factor MS-x: si el núcleo MS-x no solapa con el núcleo LSQR, score=0 cuenta como evidencia 'evaluada' y baja el score; pero ausencia total de overlap puede ser por desalineación de grilla, no por falta de favorabilidad**
- file: terraquantum-backend\services\favorability_service.py:292-301
- impacto: Jaccard top-10% vs top-10%: dos núcleos pequeños rara vez ocupan exactamente las mismas celdas, así que el overlap es estructuralmente bajo aun con buena correlación. El score de soporte MS-x estará sesgado a la baja por construcción geométrica (no por física). Con peso 0.10 puede deprimir injustamente la favorabilidad. Además no valida que la grilla MS-x esté alineada con la de densidad más allá de bounds (_validate_indices), por lo que un desfase de origen produce overlap espurio=0.
- fix: Usar correlación/IoU dilatada (buffer de 1 celda) o coeficiente de solapamiento (overlap/min) en vez de Jaccard estricto; validar co-registro de grillas.
### [P2] favor-structural-grad-norm-11 | dim:2 (normalización que colapsa rango) | conf:media
**Gradiente estructural normalizado por (rango_densidad/dx) → con un solo outlier de densidad el denominador explota y el score colapsa a ~0**
- file: terraquantum-backend\services\favorability_service.py:236-241
- impacto: max_grad_ref usa min/max crudos (sensibles a outliers). Un único bloque con densidad anómala (o el default 2.6 vs un alto contraste) infla density_range, el denominador crece y p90_grad/max_grad_ref tiende a 0, colapsando el factor a un score artificialmente bajo. La normalización por rango no robusto hace el score dependiente de un solo valor extremo, no de la estructura.
- fix: Normalizar por un rango robusto (p98-p2) o por la desviación MAD, consistente con _factor_anomaly_intensity que sí usa MAD.
### [P2] favor-quality-gate-logic-12 | dim:1 (correctitud lógica) / 8 (resultado engañoso) | conf:media
**quality_gate: el cap por incertidumbre solo se activa si overall_level no es GOOD/MEDIUM; un modelo GOOD con incertidumbre altísima nunca recibe cap**
- file: terraquantum-backend\services\favorability_service.py:391-413
- impacto: La rama de incertidumbre (cap 60/40) es inalcanzable cuando overall_level es GOOD o MEDIUM, porque el if-elif corta antes. Un modelo etiquetado GOOD por technicalSummary pero con uncertainty_score muy alto recibe multiplier=1.0 y cap=None → score no penalizado por incertidumbre vía esta puerta (solo por uncertainty_gate multiplier=1-0.5*u, máx 0.5). El gate de calidad y el de incertidumbre no son ortogonales como sugiere el diseño.
- fix: Aplicar cap por incertidumbre independientemente del overall_level (min de ambos caps), o documentar que GOOD/MEDIUM ignoran la incertidumbre intencionalmente.
### [P2] favor-empty-factor-score0-13 | dim:8 (fallback silencioso) | conf:baja
**Factores con density_1d.size==0 devuelven score=0.0 con status='evaluated' → contaminan el promedio ponderado como evidencia negativa real**
- file: terraquantum-backend\services\favorability_service.py:123-134
- impacto: Si el array de densidad está vacío (o casi), _factor_anomaly_intensity/_factor_core_coherence devuelven value=0.0 pero status='evaluated', así que _aggregate_score los cuenta en numerador/denominador como evidencia evaluada con 0 puntos, en vez de marcarlos not_evaluated. Esto baja el score como si hubiera evidencia negativa cuando en realidad NO hay datos. (En la práctica _numeric_array ya lanza si está vacío, mitigando, pero la rama size==0 es código muerto-engañoso que documenta una intención peligrosa.)
- fix: Cuando size==0, devolver status='not_evaluated' y value=None para que el factor se excluya del promedio, no lo penalice.
### [P2] econ-bulk-mass-unit-14 | dim:2 (unidades inconsistentes) | conf:alta
**bulk_rock_mass_kg = block_volume(m3) * density(t/m3) está en TONELADAS pero la columna se llama _kg (factor 1000 de error de unidad latente)**
- file: terraquantum-backend\exploration\gravimetry.py:1738-1775
- impacto: density está en t/m3 (default 2.6) y block_volume en m3, por lo que el producto está en TONELADAS, no kg. La columna se exporta como 'bulk_rock_mass_kg'. Cualquier consumidor que asuma kg estará 1000× alto; el comentario de renombrado (tonnage->bulk_rock_mass_kg) confirma que es tonelaje disfrazado de kg. Aunque pit_design no usa esta columna (usa tonnage default=0), el report y futuros consumidores sí, y la etiqueta de unidad es físicamente falsa.
- fix: Renombrar a bulk_rock_mass_t o multiplicar por 1000 si realmente se quieren kg. Fijar la convención de unidad de densidad (t/m3) explícitamente.
### [P3] econ-favorability-stale-cache-15 | dim:7 (reproducibilidad/provenance) | conf:media
**El endpoint de favorabilidad sirve favorability.json cacheado sin validar versión/hash → resultados obsoletos tras recalibrar**
- file: terraquantum-backend\api\favorability_api.py:20-27
- impacto: Si existe favorability.json se devuelve tal cual, sin comparar VERSION ('0.1') ni hash del block model. Tras cambiar pesos (FACTOR_WEIGHTS) o re-invertir, el score servido queda desactualizado silenciosamente. Falta de invalidación de cache por provenance — problema de reproducibilidad industrial.
- fix: Incluir version + hash del block_model en el JSON y recomputar si no coinciden con el código/datos actuales.
### [P3] econ-rename-glb-windows-16 | dim:3 (robustez) | conf:media
**os.rename de .glb.tmp a .glb falla en Windows si el destino existe (no atómico cross-platform)**
- file: terraquantum-backend\services\pit_design_service.py:519-520
- impacto: En Windows os.rename lanza FileExistsError si final_glb ya existe (a diferencia de POSIX). Como job_id es uuid el choque es raro, pero ante reintento o colisión el endpoint revienta con 500 no manejado en vez de devolver error estructurado. El entorno es Windows 11.
- fix: Usar os.replace() en vez de os.rename() para sobrescritura atómica cross-platform.
### [P2] econ-fallback-shell-passes-as-pit-17 | dim:8 (fallback que finge resultado) | conf:media
**El fallback de cubos (build_fallback_phase_block_scene) presenta cajas como diseño de pit; el guardrail solo loguea, no degrada el status**
- file: terraquantum-backend\services\pit_design_service.py:479-502
- impacto: Cuando la malla con bancos sale vacía (común en modelos pequeños/sintéticos) se generan cubos por bloque y se exporta como GLB con status='done' y pit_mesh_mode='fallback_block_shell'. Para una corrida real (project_run) esto NO es un pit defensible, pero el código solo emite un warning de log; la respuesta HTTP sigue siendo 'done' con métricas NPV. El usuario recibe un 'pit' que son cubos. El warning de bajo-resolución va en el campo 'warning' pero el resultado se presenta como exitoso.
- fix: Para source_mode=='project_run', si pit_mesh_mode=='fallback_block_shell', degradar a status='warning'/'conceptual' y marcar las métricas como no-defendibles en la respuesta, no solo en logs.

## api-app-schemas  (P0:1 P1:5 P2:6 P3:5) archivos:43
### [P0] grav-gate-01 | dim:8 (fallbacks silenciosos) / 1 (correctitud) | conf:alta
**El 'hard gate' de spatial readiness es un no-op: nunca bloquea ni advierte**
- file: terraquantum-backend/api/gravity_import_api.py:480-531
- impacto: Un CSV SIN datos espaciales (NO_SPATIAL_DATA, level_rank=0) produce igualmente un modelo 3D 'invertido' que se persiste como resultado válido con georef MISSING, sin error ni bloqueo. La docstring promete 'Lanza HTTPException(422) si el nivel espacial es insuficiente' pero el código no lo hace nunca. Se finge un resultado georreferenciable sobre datos que no lo son: el pecado capital del proyecto. _raise es dead code.
- fix: Implementar realmente el gate: para niveles NO_SPATIAL_DATA / LOCAL_* exigir acknowledge_spatial_risk=True y llamar _raise() si falta; o renombrar la función a algo honesto (_annotate_spatial_readiness) y mover los warnings al payload. La docstring debe coincidir con el comportamiento.
- VERIFICACION: incierto (sev->) :: verificacion fallo
### [P1] grav-resp-01 | dim:4 (contratos de API) | conf:alta
**GeophysicsInvertResponse declarado pero nunca cableado; los endpoints devuelven dict crudo sin validar**
- file: terraquantum-backend/api/geophysics_api.py:48-76, 101-123
- impacto: No hay garantía de contrato entre backend y frontend en el endpoint físico central. Cambios en el dict del servicio (claves renombradas, campos faltantes) no disparan error de validación; el frontend recibe formas inconsistentes silenciosamente. El schema documentado en OpenAPI no refleja la respuesta real.
- fix: Cablear response_model=GeophysicsInvertResponse en /geophysics-invert (versión síncrona) y validar el dict del servicio contra el modelo, o construir y retornar la instancia Pydantic explícitamente.
- VERIFICACION: incierto (sev->) :: verificacion fallo
### [P1] grav-err200-01 | dim:3 (robustez) / 4 (contratos) | conf:alta
**Fallo de import de CSV devuelve HTTP 200 con body {"status":"error"} en /gravity-import/invert**
- file: terraquantum-backend/api/gravity_import_api.py:677-705
- impacto: Un CSV malformado/rechazado produce respuesta 200 OK. Clientes HTTP que chequean response.ok / status code (incluido el proxy Next.js) interpretan el fallo como éxito y deben inspeccionar el cuerpo. Inconsistente con el resto de errores del mismo endpoint que sí usan HTTPException 422/500.
- fix: Devolver JSONResponse(status_code=422, content=...) para el caso import_result.status != 'ok', manteniendo el cuerpo de diagnóstico.
- VERIFICACION: incierto (sev->) :: verificacion fallo
### [P1] grav-masterkey-01 | dim:5 (seguridad) | conf:alta
**Comparación de master key no es de tiempo constante (timing attack)**
- file: terraquantum-backend/api/keys_api.py:25-26
- impacto: La comparación con '!=' aborta en el primer byte distinto, filtrando información de temporización que permite recuperar la master key byte a byte. La master key controla creación/revocación de TODAS las API keys del sistema (acceso total). En auth.py los hashes SHA-256 se comparan vía SQL exacto (aceptable), pero la master key se compara en plano.
- fix: Usar secrets.compare_digest(x_tq_master_key, TQ_MASTER_KEY) tras verificar que TQ_MASTER_KEY no esté vacío.
- VERIFICACION: incierto (sev->) :: verificacion fallo
### [P1] grav-vtr-traversal-01 | dim:5 (seguridad) | conf:media
**export_vtr usa get_run_dir sin sanitizar project_id/run_id (path traversal)**
- file: terraquantum-backend/api/geophysics_api.py:141-162
- impacto: project_id/run_id provienen de la URL sin validación. En POSIX un valor como '..%2f..%2f..%2fetc' (o segmentos '..') puede escapar de PROJECTS_DIR. Aunque otros endpoints (status) pasan por clean_trace_context, export_vtr llama get_run_dir crudo. Permite leer/servir archivos .vtr fuera del árbol de proyectos o causar errores de ruta. clean_trace_id sí rechaza '..' pero aquí no se invoca.
- fix: Reemplazar get_run_dir(project_id, run_id) por una resolución que pase por clean_trace_context(project_id, run_id) y verificar que vtr_path.resolve() esté dentro de PROJECTS_DIR.resolve().
- VERIFICACION: incierto (sev->) :: verificacion fallo
### [P1] grav-chat-filter-01 | dim:1 (correctitud) / 8 (resultado engañoso) | conf:alta
**Filtro de compliance del chat usa lista de palabras en inglés y substring, no cubre español ni evita falsos positivos**
- file: terraquantum-backend/api/chat_api.py:12-24, 76-81
- impacto: Doble fallo: (1) El modelo responde en español; 'reservas', 'recursos', 'ley', 'tonelaje', 'TIR' NO están en la lista de baneo → el guardrail JORC/NI-43-101 no detecta las violaciones reales que pretende bloquear (falso sentido de compliance). (2) substring match dispara falsos positivos: 'grade' baneado bloquea 'upgrade'/'degrade'; 'resource' bloquea texto inocuo. Compliance minero crítico que no funciona.
- fix: Banear los términos en español que el prompt prohíbe, usar coincidencia por palabra (regex \bword\b) y mantener ambos idiomas. Considerar normalización de acentos.
- VERIFICACION: incierto (sev->) :: verificacion fallo
### [P2] grav-pit-zerodiv-01 | dim:3 (robustez) / 1 (correctitud) | conf:media
**Esquemas pit/scenario sin validación de rangos: división por cero y valores negativos pasan al solver**
- file: terraquantum-backend/schemas/pit_design_schema.py:5-31
- impacto: recovery=0, price<0, pit_angle=0, steps=0, fleet_size=0 son aceptados por Pydantic. En scheduler.py el fleet_size y depths se usan en divisiones (dist = depth/(ramp/100)); steps=0 en un sweep genera rango vacío o ZeroDivision. Como el endpoint traga todo en 500 'Error interno', el usuario no recibe diagnóstico del input inválido. (Routers económicos OFF por defecto, de ahí P2.)
- fix: Añadir restricciones Pydantic: price/recovery/costos gt=0, pit_angle gt=0 lt=90, steps ge=1, fleet_size ge=1, discount_rate ge=0. Devolver 422 con el ValidationError en vez de tragar en 500.
### [P2] grav-status-nan-01 | dim:3 (robustez) / 4 (contratos) | conf:media
**/geophysics-status devuelve el JSON de disco sin _sanitize_nan; NaN en métricas rompe JSON estándar**
- file: terraquantum-backend/api/geophysics_api.py:95-98
- impacto: Si métricas (misfit, etc.) contienen NaN/Inf (común en inversiones degeneradas), Python json.dumps por defecto emite 'NaN'/'Infinity', que no es JSON válido (RFC 8259). El proxy/parser del frontend (JSON.parse estricto) falla — coincide con la clase de bug 'no llega JSON válido' del proyecto.
- fix: Aplicar _sanitize_nan (o json con allow_nan=False + reemplazo) al cuerpo devuelto por /geophysics-status, y al escribir schedule.json en update_run_status.
### [P2] grav-favgate-01 | dim:4 (contratos) / 8 (fallbacks) | conf:media
**favorability_api devuelve cache de disco crudo bajo response_model sin garantía de forma**
- file: terraquantum-backend/api/favorability_api.py:13-48
- impacto: Si un favorability.json en cache fue escrito por una versión previa del schema (campos faltantes), response_model=FavorabilityResult lanzará 500 en validación al servir cache antiguo, en vez de degradar o recomputar. El cache no se versiona (no hay 'version' verificada al leer).
- fix: Validar el cache contra el schema antes de servirlo; si falla, recomputar. Incluir y verificar el campo 'version' al leer el cache.
### [P2] grav-cors-01 | dim:5 (seguridad) | conf:baja
**CORS allow_credentials=True con orígenes desde env; riesgo si CORS_ALLOWED_ORIGINS se configura con '*'**
- file: terraquantum-backend/main.py:92-104
- impacto: Si en deploy alguien fija CORS_ALLOWED_ORIGINS=* (patrón común), Starlette con allow_credentials=True reflejará el Origin permitiendo que cualquier sitio haga requests autenticadas con cookies/credenciales. Default local es seguro, pero no hay guardrail contra la mala configuración en producción.
- fix: Rechazar/loggear si '*' aparece en CORS_ORIGINS cuando allow_credentials=True; documentar que en prod se enumeren orígenes explícitos.
### [P2] grav-blockmodel-noauth-01 | dim:4 (contratos) / 3 (robustez) | conf:media
**/block-model y /block-model-arrow sin validación de project_id/run_id ni response_model; project_id=None por defecto**
- file: terraquantum-backend/api/block_model_api.py:14-31
- impacto: project_id/run_id None caen a fallback de modelo legacy (resolve_block_model_reference → DEFAULT_BLOCK_MODEL_PATH) sirviendo un block model arbitrario por defecto en vez de exigir contexto explícito — fallback silencioso. limit sin límite superior permite payloads enormes. Errores del servicio en /block-model (no Arrow) no se capturan → 500 sin forma definida.
- fix: Validar project_id/run_id con clean_trace_context, acotar limit (ej. le=200000) y envolver errores; evitar el fallback silencioso a modelo legacy cuando no hay contexto.
### [P2] grav-sweep-block-01 | dim:6 (rendimiento/escalabilidad) | conf:media
**/geophysics-sensitivity-sweep y /scenario-sweep son síncronos y bloqueantes en el event loop**
- file: terraquantum-backend/api/geophysics_api.py:101-123
- impacto: Aunque def-sin-async corre en threadpool (no bloquea el loop directamente), agota el threadpool de Starlette con trabajo pesado de minutos; sin rate-limit en el sweep geofísico (sí lo hay en /invert). Varias requests concurrentes saturan el servidor. La arquitectura async (Celery) existe pero estos endpoints no la usan.
- fix: Rutear los sweeps a Celery (async_api) o limitarlos con @limiter y un cap de concurrencia; documentar el costo.
### [P3] grav-status-public-01 | dim:5 (seguridad) | conf:baja
**Endpoints de estado/detalle leen disco sin auth propia más allá del middleware global; sin validación cuando TQ_AUTH_ENABLED=false (default)**
- file: terraquantum-backend/core/config.py:60
- impacto: Por defecto TODA la API (incluyendo /project-runs que enumera proyectos y rutas de disco en system-status) queda sin autenticación. Es 'dev default' documentado, pero combinado con BACKEND_HOST=0.0.0.0 (config.py:25) expone el backend en todas las interfaces sin auth si se levanta tal cual.
- fix: Documentar/forzar TQ_AUTH_ENABLED=true cuando host!=127.0.0.1; o default a 127.0.0.1.
### [P3] grav-sysstatus-info-01 | dim:5 (seguridad) | conf:media
**/system-status expone rutas absolutas del filesystem del servidor**
- file: terraquantum-backend/api/system_api.py:37-59
- impacto: Filtra la estructura de directorios absoluta del host (información útil para un atacante en combinación con el path traversal de export_vtr). Innecesario para un cliente.
- fix: Quitar las rutas absolutas del payload público o restringir /system-status a auth de master key.
### [P3] grav-modeldict-dup-01 | dim:9 (código duplicado) | conf:media
**model_to_dict y _safe_filename_part duplicados en múltiples módulos (deriva potencial)**
- file: terraquantum-backend/api/gravity_import_api.py:164-165
- impacto: Lógica clonada (serialización Pydantic, saneo de NaN, georef fallback) repartida entre API y core/geo_utils; cambios en una copia no se propagan. _MISSING_FOOTPRINT_BASE existe en geo_utils.py:78 y también _build_missing_footprint en gravity_import_api.py:418 con campos casi iguales pero no idénticos (warnings/precision_notes manejados distinto).
- fix: Centralizar model_to_dict y _sanitize_nan en core/, y unificar la construcción de 'missing footprint' en geo_utils.
### [P3] grav-schemadefault-01 | dim:8 (fallbacks que fingen resultados) / 2 (física) | conf:baja
**density_min default 2.6 / density_max 4.2 en el schema: clip petrofísico que enmascara contraste real**
- file: terraquantum-backend/schemas/geophysics_schema.py:100-109
- impacto: Por defecto la inversión recorta la densidad recuperada al rango [2.6, 4.2] t/m³ aunque el solver físico produzca valores fuera. Para depósitos de magnetita masiva/cromita (>4.2) el resultado queda saturado al borde sin avisar, dando un modelo plausible pero físicamente truncado. El usuario debe saber subir density_max manualmente; el default impone roca granítica.
- fix: Documentar el clip en el reporte de salida (flag 'density_clipped': true cuando se alcanza el bound) para que un resultado saturado no se confunda con uno físicamente resuelto.
### [P3] grav-asyncstatus-01 | dim:8 (fallbacks) / 3 (robustez) | conf:baja
**GET /api/async/tasks devuelve progress=1.0 por defecto cuando result.successful(), enmascarando tareas sin info**
- file: terraquantum-backend/api/async_api.py:104-118
- impacto: Para un task_id desconocido, Celery devuelve state=PENDING (indistinguible de 'encolado pero inexistente'). El endpoint no diferencia 'task no existe' de 'task en cola', devolviendo PENDING/progress=0 como si fuera válido. Cliente no puede detectar un task_id inválido.
- fix: Verificar existencia del task (p.ej. result.state != 'PENDING' o consultar backend) y devolver 404 para task_id desconocido.

## security-config  (P0:2 P1:2 P2:7 P3:1) archivos:27
### [P0] sec-secret-01 | dim:5-SEGURIDAD / 7-PROVENANCE | conf:alta
**Clave privada RSA real de Service Account de GCP en texto plano en el working tree**
- file: terraquantum-backend/credenciales_gee.json:5
- impacto: Es una clave privada RSA de una Service Account de GCP REAL (project_id=terraquantum-backend, client_id=115925718198019666628), no un placeholder. Aunque verifiqué con git que NO esta trackeada ni aparece en el historial (esta cubierta por .gitignore: backend/.gitignore:23 'credenciales_gee.json'), el archivo vive en disco sin cifrar dentro de OneDrive (sincronizado a la nube de Microsoft). Cualquiera con acceso al disco, a la cuenta de OneDrive, o que reciba el directorio comprimido obtiene credenciales activas de GCP. Es un secreto criptografico de larga vida sin rotacion ni vault.
- fix: Rotar/revocar YA esta key en GCP IAM (asumir comprometida por estar en OneDrive sin cifrar). No almacenar el JSON en el repo ni en carpeta sincronizada: inyectar via Secret Manager / variable de entorno GOOGLE_APPLICATION_CREDENTIALS apuntando a una ruta fuera de OneDrive, o montar como secreto en runtime. Confirmar que el .gitignore la cubre (ya lo hace) y agregar pre-commit hook (gitleaks/trufflehog).
- VERIFICACION: incierto (sev->) :: verificacion fallo
### [P0] sec-secret-02 | dim:5-SEGURIDAD / 4-CONTRATOS | conf:alta
**NEXT_PUBLIC_TQ_API_KEY expone la API key de auth a TODOS los navegadores (auth inutil)**
- file: terraquantum-web/lib/terraquantum/frontendApi.ts:703 (y 1066)
- impacto: Next.js INLINE estáticamente toda variable con prefijo NEXT_PUBLIC_ dentro del bundle JS que se envia al navegador. Como frontendApi.ts (deleteRun) se usa desde HistorialView.tsx (componente cliente), la API key 'tq_8YBe11uI21hszYlF9VjdRbLDOYC8OUbc6vyLC4FQd9E' queda escrita en el JavaScript publico y es leible por cualquier visitante con DevTools. Esto anula por completo el ApiKeyMiddleware: un atacante con la key puede llamar e incluso DELETE /projects/{id}/runs/{id} en el backend. La auth da una falsa sensacion de seguridad.
- fix: Eliminar TODO uso de NEXT_PUBLIC_TQ_API_KEY. Las llamadas con credenciales deben pasar por route handlers server-side de Next (app/api/*) que usan process.env.TQ_API_KEY (sin prefijo NEXT_PUBLIC, como ya hace backend.ts:46). El cliente nunca debe portar la key. Rotar la key tq_8YBe... ya expuesta.
- VERIFICACION: incierto (sev->) :: verificacion fallo
### [P1] sec-secret-03 | dim:5-SEGURIDAD | conf:alta
**API key real versionable en .env.local (TQ_API_KEY con valor de produccion)**
- file: terraquantum-web/.env.local:3-4
- impacto: El .env.local contiene una API key con formato real (tq_ + token_urlsafe, coincide con el formato de core/auth.py:37 'tq_' + secrets.token_urlsafe(32)). Verifique que NO esta en git ni en el historial (cubierto por web/.gitignore:y .gitignore raiz .env.*). Pero esta en disco en OneDrive sincronizado y se reutiliza la MISMA key para server y client, ademas hardcodeada en vez de generada por entorno. Si alguna vez se hace 'git add -f' o se comparte el folder, la key se filtra.
- fix: No guardar valores reales en .env.local versionable; usar gestor de secretos o .env.local realmente local (fuera de OneDrive). Separar key server de cualquier uso client (ver sec-secret-02). Documentar rotacion.
- VERIFICACION: incierto (sev->) :: verificacion fallo
### [P2] sec-tmpfiles-04 | dim:9-CODIGO MUERTO | conf:alta
**Archivos de diagnostico _tmp olvidados en la raiz del backend (codigo muerto ejecutable)**
- file: terraquantum-backend/_diag_mag_tmp.py:1-29 (y _test_mag_route_tmp.py:1-52)
- impacto: Scripts de diagnostico transitorios dejados en el repo raiz. _test_mag_route_tmp.py invoca run_geophysics_inversion() (codigo de produccion) con asserts; no son tests bajo pytest (no estan en tests/, no usan fixtures). Manipulan sys.path en runtime. En un proyecto que aspira a 'industrial' son ruido, riesgo de ejecucion accidental y senal de falta de higiene. No tienen guards de seguridad ni se limpian.
- fix: Borrar ambos _*_tmp.py o moverlos a tests/ como casos parametrizados reales con pytest. Anadir patron *_tmp.py al .gitignore o a un lint de CI que bloquee archivos _tmp.
### [P2] sec-bat-05 | dim:5-SEGURIDAD / 6-PORTABILIDAD / 9-DEUDA | conf:alta
**Scripts .bat con rutas absolutas hardcodeadas al perfil del usuario (rompen en otra maquina)**
- file: terraquantum-backend/run-smoke-test.bat:9 (y terraquantum-web/run-frontend-smoke-test.bat:9)
- impacto: Rutas absolutas al perfil 'marti' embebidas en scripts versionados. Ademas la ruta apunta a '...\Documentos\terraquantum-backend' (sin la carpeta 'TerraQuantum' intermedia que tiene el repo real C:\Users\marti\OneDrive\Documentos\TerraQuantum\terraquantum-backend) -> el cd fallara silenciosamente y el smoke-test correra en el directorio equivocado, dando un PASS/FAIL no fiable. Filtra el username del autor y es no-portable. Contrasta con start-backend.bat:10 que usa correctamente cd /d %~dp0.
- fix: Reemplazar las rutas absolutas por %~dp0 (relativo al script) como ya hacen start-backend.bat y start-frontend.bat. Eliminar referencias al path personal del usuario.
### [P1] sec-auth-06 | dim:5-SEGURIDAD / 8-FALLBACK SILENCIOSO | conf:alta
**Auth en produccion desactivada por defecto (TQ_AUTH_ENABLED=false) — fail-open**
- file: terraquantum-backend/core/config.py:60
- impacto: El default es fail-OPEN: si nadie setea TQ_AUTH_ENABLED el middleware deja pasar TODA peticion sin autenticar. El docker-compose.yml (lineas 10-16) NO define TQ_AUTH_ENABLED ni TQ_MASTER_KEY, asi que el despliegue Docker 'oficial' arranca el backend completamente abierto en 0.0.0.0:8010 (Dockerfile:16 host 0.0.0.0). Para un sistema 'industrial' la postura segura debe ser fail-closed o al menos forzar config explicita en prod.
- fix: Invertir el default a seguro (auth ON salvo TQ_DEV_MODE explicito), o hacer que el arranque aborte si TQ_AUTH_ENABLED!=true y no es entorno dev. Definir TQ_AUTH_ENABLED=true y TQ_MASTER_KEY en docker-compose/prod. Loggear un WARNING ruidoso cuando arranca sin auth.
- VERIFICACION: incierto (sev->) :: verificacion fallo
### [P2] sec-auth-07 | dim:5-SEGURIDAD | conf:media
**Comparacion de master key no es de tiempo constante (timing attack)**
- file: terraquantum-backend/api/keys_api.py:25
- impacto: La master key (que gobierna creacion/revocacion de TODAS las API keys) se compara con != ordinario, que hace short-circuit y filtra informacion de timing byte a byte. Tambien validate_api_key compara via lookup hash (eso es ok), pero la master key es el secreto mas critico y es comparable por timing. En un endpoint expuesto permite recuperar la key con suficientes mediciones.
- fix: Usar hmac.compare_digest(x_tq_master_key, TQ_MASTER_KEY) para comparacion constante. Considerar tambien hashear la master key en reposo en vez de compararla en claro.
### [P2] sec-cors-08 | dim:5-SEGURIDAD / 4-CONTRATOS | conf:media
**CORS allow_origins desde env sin validar '*' combinado con allow_credentials=True**
- file: terraquantum-backend/core/config.py:28-32
- impacto: El .env.example advierte 'NO usar * — rompe allow_credentials=True', pero el codigo NO valida ni rechaza '*'. Si un operador setea CORS_ALLOWED_ORIGINS=* (error comun), Starlette con allow_credentials=True reflejara el Origin de cualquier sitio, habilitando que cualquier pagina haga requests autenticadas con cookies/credenciales del usuario. La defensa es solo un comentario, no codigo.
- fix: Validar en config.py: si '*' esta en CORS_ORIGINS y allow_credentials=True, abortar el arranque o forzar allow_credentials=False. No depender de un comentario en .env.example.
### [P2] sec-supply-09 | dim:7-REPRODUCIBILIDAD / 5-SEGURIDAD | conf:media
**Dependencias backend sin pin (CVE/supply-chain no reproducible) salvo el nucleo numerico**
- file: terraquantum-backend/requirements.txt:1-31
- impacto: El comentario en lineas 5-7 dice que pinean numpy/polars/scipy 'por reproducibilidad', pero deja fastapi, uvicorn, pydantic, python-multipart (este ultimo tuvo CVEs de DoS por multipart), celery, redis y google-generativeai SIN pin ni rango superior. Un 'pip install' en dos fechas distintas produce arboles de dependencias distintos: build no reproducible y exposicion a versiones nuevas vulnerables o que rompen la API. No hay lockfile (pip-tools/poetry) ni hashes. Para un sistema que se jacta de provenance SHA-256 esto es inconsistente.
- fix: Generar un lockfile con hashes (pip-compile/poetry/uv) y pinear todo. Al menos fijar fastapi, pydantic, python-multipart a versiones validadas con CVE conocidos parcheados. Anadir pip-audit/dependabot en CI.
### [P2] sec-docker-10 | dim:5-SEGURIDAD | conf:media
**Contenedores corren como root y backend bindea 0.0.0.0 sin usuario no-privilegiado**
- file: terraquantum-backend/Dockerfile:12-16
- impacto: Ninguno de los dos Dockerfile crea ni usa un usuario no-root (falta USER appuser). Ambos procesos corren como root dentro del contenedor; combinado con COPY . . (que copia TODO el contexto, potencialmente incluyendo credenciales_gee.json y .env locales si estan en el build context y no excluidos por .dockerignore) eleva el impacto de un RCE. El backend ademas escucha en 0.0.0.0 por defecto.
- fix: Anadir un usuario no-root (RUN adduser --disabled-password app; USER app) en ambos Dockerfile. Crear .dockerignore que excluya credenciales_gee.json, .env*, data/, tmp/. Verificar que COPY . . no arrastra secretos.
### [P2] sec-gee-11 | dim:8-FALLBACK SILENCIOSO | conf:media
**Fallback silencioso de GEE: credenciales invalidas degradan a datos mock sin senalar al usuario**
- file: terraquantum-backend/core/gee_client.py:25-49
- impacto: Si las credenciales faltan, expiran o son rechazadas por GEE, init_gee() retorna sin error y _gee_available queda False; el resto del sistema continua con datos MOCK. Solo queda un warning en logs estructurados que nadie mira en runtime. Es el 'pecado capital' del proyecto: un resultado que parece valido (satelite/territorio) puede estar construido sobre datos falsos sin que el operador lo sepa. No hay flag visible en la respuesta de API que diga 'GEE degradado a mock'.
- fix: Propagar el estado is_available() a la respuesta de las APIs que dependen de GEE y marcarlo (badge 'MOCK/DEGRADED'). En modo produccion, fallar ruidosamente (o devolver 503) si se pidio dato satelital real y GEE no esta disponible, en vez de servir mock silencioso.
### [P3] sec-celery-12 | dim:5-SEGURIDAD | conf:baja
**Celery/Redis por defecto a redis://localhost:6379 sin password (broker sin auth)**
- file: terraquantum-backend/core/config.py:47-48
- impacto: El default y la doc instruyen levantar Redis con el puerto 6379 publicado y sin contrasena. Redis sin auth es un vector clasico de RCE/exfiltracion (CONFIG SET dir + module load). Si se publica el puerto en un host accesible, el broker de tareas queda abierto. Celery deserializa solo JSON (bien, celery_app.py:28 accept_content=['json']), lo que mitiga el RCE por pickle, pero el broker sigue sin auth.
- fix: Default y docs deben usar Redis con requirepass / ACL y no publicar 6379 al exterior. Documentar rediss:// con TLS para remoto. No publicar el puerto en docker salvo red interna.

## test-quality  (P0:0 P1:6 P2:7 P3:4) archivos:25
### [P1] tests-validation-not-collected-01 | dim:9 (codigo muerto) / 8 (falso resultado) | conf:alta
**Toda la carpeta scripts/validation/ NUNCA se ejecuta por pytest (testpaths=tests)**
- file: terraquantum-backend/pytest.ini:2
- impacto: Decenas de 'tests' de validacion (QA/QC, validacion de input, fit diagnostics, sensitivity, focusing) dan la apariencia de cobertura pero jamas se ejecutan en CI. Una regresion en validate_geophysics_input o build_fit_diagnostics pasaria inadvertida.
- fix: Mover los tests reales a tests/ con prefijo test_ y funciones test_*, o anadir scripts/validation a testpaths. Convertir run_tests()/main() en asserts pytest.
- VERIFICACION: incierto (sev->) :: verificacion fallo
### [P1] tests-script-no-testfunc-02 | dim:8 (falso resultado) / 7 (provenance) | conf:alta
**Benchmarks 'cientificos' y regresiones en tests/ no tienen funciones test_ -> pytest colecta 0 asserts**
- file: terraquantum-backend/tests/synthetic_recovery_benchmark.py:299, 856-905
- impacto: Los 'certificados de recuperacion' que sustentan el claim 'funciona' NO corren en pytest. Solo se ejecutan si alguien los invoca manualmente. CI verde no implica que la recuperacion sintetica pase.
- fix: Envolver cada benchmark en una funcion test_ con asserts duros sobre las metricas (pearson_r, depth_err) en lugar de solo imprimir/escribir JSON.
- VERIFICACION: incierto (sev->) :: verificacion fallo
### [P1] tests-benchmark-ci-always-pass-03 | dim:8 (falso resultado) | conf:alta
**synthetic_recovery_benchmark en modo --ci siempre hace exit(0), sin umbral**
- file: terraquantum-backend/tests/synthetic_recovery_benchmark.py:893-902
- impacto: Si este benchmark llegara a engancharse en un pipeline CI con --ci, daria verde aunque la inversion colapse (POOR). Es un gate placebo que finge validar la fisica.
- fix: Fijar un umbral real (ej pearson_r>=0.7) y exit(1) si no se cumple, incluso en --ci.
- VERIFICACION: incierto (sev->) :: verificacion fallo
### [P1] tests-r37-gate-conditional-assert-04 | dim:3 (robustez) / 8 (falso resultado) | conf:alta
**Tests del gate REGIONAL_SCALE solo asertan dentro de `if status==422`: pasan aunque el gate nunca dispare**
- file: terraquantum-backend/tests/test_r37_regional_scale_gate.py:149-215
- impacto: El gate de escala regional (P0 de seguridad fisica: evita invertir a escala equivocada) podria estar roto y estos tests seguirian verdes porque su asercion principal es opcional.
- fix: Construir CSVs deterministas que garanticen 422 y asertar status_code==422 de forma incondicional; no envolver asserts en `if 422`.
- VERIFICACION: incierto (sev->) :: verificacion fallo
### [P1] tests-joint-deadthreshold-05 | dim:1 (correctitud) / 8 (falso resultado) | conf:alta
**test_joint_structural_coupling declara THRESHOLD r>=0.3 pero NUNCA computa ni asierta el Pearson r**
- file: terraquantum-backend/tests/test_joint_structural_similarity.py:16, 79-89
- impacto: El acoplamiento estructural cross-gradient (la justificacion entera de la inversion conjunta) no esta testeado. Un joint que produzca modelos descorrelacionados pasaria.
- fix: Computar |grad| de ambos modelos recuperados y asertar np.corrcoef >= THRESHOLD_JOINT_PEARSON_R, ademas comparar contra dos inversiones independientes.
- VERIFICACION: incierto (sev->) :: verificacion fallo
### [P1] tests-validate-output-hardcoded-pass-06 | dim:8 (fallback que finge resultado) | conf:alta
**validate_output.py: checks de joint coupling con `ok = True` hardcodeado (siempre pasan)**
- file: terraquantum-backend/scripts/validation/validate_output.py:345-362
- impacto: El 'reporte de validacion completo' suma estos checks always-true al conteo passed/total, inflando artificialmente la tasa de aprobacion y dando un veredicto APROBADO con acoplamiento joint posiblemente nulo.
- fix: Eliminar los checks decorativos del conteo o convertirlos en umbrales reales (ej E_norm_final < MAX_E_NORM_WARN como fallo).
- VERIFICACION: incierto (sev->) :: verificacion fallo
### [P2] tests-validate-output-tolerant-threshold-07 | dim:8 (falso resultado) | conf:alta
**validate_output.py acepta hasta 2 fallos y omite checks sin penalizar (umbrales laxos)**
- file: terraquantum-backend/scripts/validation/validate_output.py:179-180, 242, 246, 320
- impacto: Un modelo puede fallar densidades-en-bounds y misfit y aun asi pasar SANITY. Si el endpoint deja de emitir fitDiagnostics, FIT devuelve True (verde) en lugar de senalar la ausencia. Es tolerancia que enmascara degradacion.
- fix: Hacer obligatorios los checks fisicos criticos (densidad en bounds, misfit) y fallar si faltan metricas en lugar de retornar True.
### [P2] tests-project-run-self-compare-08 | dim:7 (reproducibilidad) / 8 (falso resultado) | conf:alta
**test_project_run_flow compara un run contra SI MISMO (npv_delta trivialmente 0)**
- file: terraquantum-backend/scripts/validation/test_project_run_flow.py:222-240
- impacto: El 'test' de comparacion de runs no valida nada de la logica de diff (no detectaria si compare_project_runs devolviera basura para runs distintos). Confianza falsa en la feature de comparacion.
- fix: Ejecutar dos runs con parametros distintos y asertar que npv_delta != 0 y refleja la diferencia esperada.
### [P2] tests-project-run-truthy-only-09 | dim:8 (falso resultado) | conf:alta
**test_project_run_flow valida existencia/truthiness, no correctitud fisica de la inversion**
- file: terraquantum-backend/scripts/validation/test_project_run_flow.py:109-126
- impacto: El flujo end-to-end principal pasa con CUALQUIER salida no vacia, incluso un modelo degenerado/uniforme. Es exactamente el patron que hace que 'todas las IAs digan que funciona'.
- fix: Anadir asserts sobre misfit_error_percent, rango de densidad y posicion de la anomalia frente a un caso sintetico conocido.
### [P2] tests-noexception-only-10 | dim:8 (falso resultado) | conf:alta
**Multiples tests integration solo verifican 'no lanza excepcion' + storageMode, sin correctitud**
- file: terraquantum-backend/tests/test_lsqr_inversion.py:51-67
- impacto: Estos integration tests certifican que el pipeline corre sin crashear, no que produzca fisica correcta. Una inversion que devuelve densidades planas o ruido pasaria.
- fix: Acoplar estos happy-path a un ground truth sintetico (como audit_groundtruth) y asertar metricas de recuperacion.
### [P3] tests-doi-tautology-11 | dim:8 (falso resultado) | conf:alta
**test_doi_index_interpretation es una tautologia aritmetica (no prueba el codigo de produccion)**
- file: terraquantum-backend/tests/test_doi_calibration.py:108-124
- impacto: Es un test vacio que solo verifica que 0.01/0.1==0.1. Da impresion de cobertura DOI sin tocar el calculo real de doi_raw.
- fix: Eliminar o reemplazar por una llamada al calculador DOI real con un caso de referencia.
### [P2] tests-input-validation-any-exception-pass-12 | dim:3 (robustez) / 8 (falso resultado) | conf:alta
**test_geophysics_input_validation cuenta CUALQUIER excepcion como PASS (incluso un crash inesperado)**
- file: terraquantum-backend/scripts/validation/test_geophysics_input_validation.py:62-65
- impacto: Un caso que deberia rechazarse con ValueError especifico pero que en su lugar crashea con AttributeError contaria como exito. Enmascara fallos de validacion de input (input malformado, NaN, division por cero).
- fix: Asertar el tipo y mensaje de excepcion esperado por caso; no tratar Exception generica como aprobacion.
### [P2] tests-fitdiag-bad-not-asserted-13 | dim:1 (correctitud) / 8 (falso resultado) | conf:alta
**test_geophysics_fit_diagnostics caso 'ajuste malo' no verifica que el fit_level sea malo**
- file: terraquantum-backend/scripts/validation/test_geophysics_fit_diagnostics.py:94-100
- impacto: El test del peor caso pasaria aunque build_fit_diagnostics clasifique un ajuste pesimo como GOOD. La logica de clasificacion de calidad de ajuste queda sin validar en su rama mas importante.
- fix: Asertar que el caso malo produce fit_level no-GOOD y normalized_rmse por encima de un umbral.
### [P3] tests-spatial-readiness-self-consistent-14 | dim:8 (ground-truth circular) | conf:media
**test_spatial_readiness_service valida un mapeo deterministico contra sus propias constantes (poca senal real)**
- file: terraquantum-backend/tests/test_spatial_readiness_service.py:260-296, 472-482
- impacto: Estos tests dan alta cobertura aparente pero son en parte circulares: comparan el output contra las constantes-fuente, no contra un valor esperado independiente. Detectan errores de cableado pero no errores de criterio de negocio.
- fix: Hardcodear los valores esperados (0.0, 45.0, 85.0...) literalmente en el test en vez de re-importar la constante del modulo bajo prueba.
### [P3] tests-grade-integrity-contradictory-assert-15 | dim:1 (correctitud) / 4 (semantica) | conf:media
**test_report_nulls_grade_by_default asierta is_demo_grade is True cuando el grade esta APAGADO**
- file: terraquantum-backend/tests/test_grade_integrity.py:80-90
- impacto: Un consumidor que lea is_demo_grade=True asumira que hay ley demo expuesta cuando avg_grade es None. El test blinda esa inconsistencia de naming en vez de detectarla.
- fix: Aclarar la semantica de is_demo_grade (deberia reflejar si se EXPUSO grade demo) y corregir el assert acorde.
### [P2] tests-audit-noassert-16 | dim:8 (falso resultado) / 7 (provenance) | conf:alta
**audit_groundtruth_validation y audit_real/phase2 escriben PASS/FAIL a JSON pero no fallan el proceso ni tienen asserts**
- file: terraquantum-backend/tests/audit_groundtruth_validation.py:208-235
- impacto: El 'certificado de auditoria industrial contra verdad-terreno analitica' siempre retorna exito al shell. Cualquier automatizacion que dependa del exit code lo veria como aprobado aunque el motor recupere mal la profundidad/masa.
- fix: Anadir `sys.exit(0 if overall_pass else 1)` al final de main() y/o exponer una funcion test_ con asserts.
### [P3] tests-r3enrich-mock-everything-17 | dim:8 (falso resultado) | conf:media
**test_r3_integration_auto_enrichment mockea ambos servicios: prueba el orquestador, no la fisica del enriquecimiento**
- file: terraquantum-backend/tests/test_r3_integration_auto_enrichment.py:99-129, 297-303
- impacto: El enriquecimiento DEM real (muestreo de elevacion, coregistro) nunca se ejerce en automatico; solo se verifica que el wrapper llama a las funciones correctas. El QA real queda relegado a 'manual deseado', que en la practica no se hace.
- fix: Anadir al menos un test que ejecute enrich_block_model_with_elevation real sobre un DEM fixture pequeno y valide las elevaciones asignadas.

## fe-render  (P0:1 P1:4 P2:5 P3:5) archivos:5
### [P0] joint-default-divergence-01 | dim:9 (codigo duplicado que diverge) + 8 (fallback silencioso que finge resultado) | conf:alta
**El worker y el hilo principal DIVERGEN en el modo joint: el worker pinta de cian voxeles sin dato joint (corrida gravity-only se ve como joint)**
- file: terraquantum-web\workers\voxelBufferBuilder.worker.ts:376-383
- impacto: El fix documentado en terraQuantumGeology.ts (ocultar voxel cuando joint_structural_score esta ausente) NO se aplico al worker. Para modelos > LOD_WORKER_THRESHOLD (50.000 voxeles) — es decir el caso de escala regional/Bushveld, el unico que usa el worker — una inversion gravity-only se renderiza ENTERA en cian corporativo como si fuera un resultado joint multi-fisica valido. El usuario ve un 'resultado joint' que no existe. Exactamente el pecado capital del proyecto. Ademas en el path principal jointThreshold default=0.6 pero en el worker la rama de ausencia ni siquiera llega al umbral.
- fix: Replicar en worker.ts la logica de geology.ts: if (jointRaw === undefined || jointRaw === null) { escribir matriz cero + color 0; continue; }. Mejor: extraer la funcion de color/visibilidad a UN solo modulo compartido importado por ambos para que no puedan divergir.
- VERIFICACION: incierto (sev->) :: verificacion fallo
### [P2] density-anomaly-negative-bypass-01 | dim:8 (fallback silencioso) + 1 (correctitud, centinela fragil) | conf:media
**density_anomaly_score negativo se trata como 'presente' (-999 centinela) y pasa a clamp01 -> 0, falseando voxeles sin anomalia como score valido**
- file: terraquantum-web\lib\terraQuantumGeology.ts:224-229, 236-237
- impacto: Se usa -999 como centinela de 'campo ausente'. Si el backend alguna vez emite literalmente -999 (improbable) o si el campo existe pero es negativo, el negativo se devuelve y luego clamp01 lo aplasta a 0, marcando el voxel como 'sin anomalia' en lugar de 'dato faltante'. La logica mezcla 'ausente' con 'cero' silenciosamente. El default density=2.6 en getVoxelModeledDensity (geology.ts:221) ademas inventa densidad de roca pais para celdas sin dato, contaminando densMin/densMax y el colormap.
- fix: Usar null/NaN explicito en vez del centinela -999 y propagar 'dato ausente' como gris neutro (como ya se hace para susceptibilidad), no como score 0. Quitar el fallback density=2.6.
### [P1] density-fallback-2.6-vs-2.75-01 | dim:8 (fallback que finge) + 1 (correctitud) | conf:alta
**Dos densidades de roca pais fallback distintas (2.6 y 2.75) coexisten y se mezclan en el mismo calculo de anomalia**
- file: terraquantum-web\lib\terraQuantumGeology.ts:138, 221, 228
- impacto: Una celda sin densidad recibe getVoxelModeledDensity=2.6, y luego getVoxelDensityAnomalyScore calcula 2.6 - 2.75 = -0.15 -> Math.max(0,...) = 0. Es decir: voxeles SIN dato producen anomalia=0 'valida' (no se distinguen de roca de fondo real). Tres constantes de densidad de fondo distintas (2.6, 2.75 x2) en el mismo pipeline garantizan inconsistencia fisica entre el color, el score y el envelope.
- fix: Una sola constante de densidad de fondo provista por backend; celdas sin densidad => NaN/gris, nunca un numero plausible inventado.
- VERIFICACION: incierto (sev->) :: verificacion fallo
### [P1] worker-only-large-models-01 | dim:9 (duplicado divergente) + 2 (escala del dominio) | conf:alta
**Modelos grandes (escala regional 157km) dependen del worker, pero el worker no aplica is_active duplicado ni respeta el fix joint -> el cuerpo real puede ocultarse o falsearse solo a esa escala**
- file: terraquantum-web\componentes\Scene3D.tsx:547, 787-792, 893-898
- impacto: Cualquier modelo de escala regional (justo el caso del 'Bug de Bushveld' citado en memoria, 157km) supera 50k voxeles y se renderiza EXCLUSIVAMENTE por el worker. Cualquier divergencia worker vs geology.ts (ver joint, ver abajo) solo se manifiesta a escala grande, que es precisamente la escala industrial. El path sincrono ademas hace fill(0) inmediato: si el worker falla o tarda, el usuario ve la malla COMPLETAMENTE vacia sin error.
- fix: Compartir un unico modulo de construccion de buffers entre worker y main. Manejar timeout/error del worker con estado de error visible, no malla vacia silenciosa.
- VERIFICACION: incierto (sev->) :: verificacion fallo
### [P3] minDensityRaw-zero-filter-01 | dim:1 (correctitud) + 3 (robustez) | conf:media
**Filtro de densidad usa null como 'sin filtro' pero un slider en 0 (minDensityRaw=0) tambien deberia ser no-op; ok, pero maxDensityRaw/minDensityRaw no validan min<=max**
- file: terraquantum-web\lib\terraQuantumGeology.ts:271-279
- impacto: Si minDensityRaw > maxDensityRaw (usuario invierte los sliders) el filtro oculta TODOS los voxeles sin avisar — pantalla vacia que parece 'no hay cuerpo'. No hay clamp ni swap ni warning.
- fix: Si minRaw>maxRaw, swap o ignorar el filtro y emitir warning de UI.
### [P2] sliceThickness-unused-01 | dim:1 (correctitud, control muerto) + 9 (codigo muerto) | conf:alta
**sliceThickness se recibe como parametro pero nunca se usa: el slice es siempre half-space, el control de grosor no hace nada**
- file: terraquantum-web\lib\terraQuantumGeology.ts:119, 426
- impacto: El control de grosor de seccion (sliceThickness) que el usuario manipula en la UI no tiene NINGUN efecto. El corte siempre oculta todo lo que esta mas alla del plano (half-space), nunca una loncha de grosor finito como anuncia el control. Funcionalidad fantasma — el usuario cree estar viendo una seccion de N metros.
- fix: Implementar el slab: visible si |axisPos - slicePosition| <= sliceThickness/2 cuando showOnlySlice; o eliminar el control si no se soporta.
### [P2] axis-convention-z-northing-01 | dim:2 (ejes intercambiados x=Norte vs Este) | conf:media
**Convencion de ejes: el comentario dice z_visual = Northing (raw z) y x = Easting, pero el tooltip y picking mezclan x/z sin etiquetar Norte/Este; riesgo de eje intercambiado no verificable en el cliente**
- file: terraquantum-web\lib\terraQuantumGeology.ts:300-310, 415-416
- impacto: El frontend asume x=Easting, z=Northing. La memoria del proyecto registra que el motor magnetico usa x=Norte, z=Este. Si un voxel magnetico llega con esa convencion, el render lo coloca con Norte y Este intercambiados — el cuerpo aparece rotado/reflejado 90 grados respecto a la realidad geografica, sin ningun aviso. No verificable solo desde el cliente pero es un riesgo de correctitud fisica latente entre subsistemas.
- fix: Definir UNA convencion de ejes canonica documentada en el contrato API y validarla; etiquetar Norte/Este explicitamente en el tooltip.
### [P3] brightness-doi-divides-range-01 | dim:2 (normalizacion) + 1 (correctitud) | conf:media
**Brillo DOI usa rango fijo (0.3 - 0.05) cableado; voxeles con sensitivity_proxy alto saturan pero el rango no se adapta a la distribucion real**
- file: terraquantum-web\lib\terraQuantumGeology.ts:517
- impacto: El denominador (0.3 - 0.05 = 0.25) y el techo 0.3 estan cableados. Si la sensibilidad real del modelo vive mayormente bajo 0.3, casi todo se ilumina parcialmente; si vive sobre 0.3, todo satura a brillo maximo y el gradiente DOI desaparece. No se normaliza contra la distribucion real de sensitivity_proxy. Identico hardcode en worker:401.
- fix: Normalizar contra percentiles reales de sensitivity_proxy del modelo, como ya se hace para densidad (P2-P98).
### [P3] console-log-hotpath-01 | dim:6 (rendimiento) + 3 (deuda) | conf:alta
**console.log por cada llamada de updateInstancedBuffers en el hot path de render (cada cambio de filtro/slice)**
- file: terraquantum-web\lib\terraQuantumGeology.ts:526-532
- impacto: Cada movimiento de slider de slice/densidad/threshold dispara updateInstancedBuffers (useLayoutEffect con muchos deps) y emite 2 console.log. En modelos grandes y con devtools abierto, logging sincrono en el hilo de render anade jank. Es codigo de instrumentacion dejado en produccion.
- fix: Gating por flag de debug o eliminar.
### [P1] probabilityFrom-default-1-01 | dim:8 (fallback que finge resultado) | conf:alta
**probabilityFrom devuelve 1 por defecto cuando falta probability, inflando scores de demo a maximo**
- file: terraquantum-web\lib\terraquantum\geophysicsModel.ts:98-100, 174-178
- impacto: Cuando un voxel no trae probability, probabilityFrom devuelve 1.0 (certeza total). El score de highlight/heatmap se reduce a (density - 2.6), es decir cualquier voxel denso se marca con probabilidad maxima inventada. El 'best target' y el heatmap se eligen sobre datos faltantes tratados como certeza absoluta — exactamente un fallback que finge un resultado valido. Para celdas sin probability el ranking es puramente densidad disfrazado de probabilidad.
- fix: Default 0 (o NaN excluido) para probability ausente; no asumir certeza.
- VERIFICACION: incierto (sev->) :: verificacion fallo
### [P1] buildGridConfig-hardcoded-8x8-01 | dim:2 (escala del dominio no se refleja) + 1 (correctitud) | conf:media
**buildGridConfig fija nx=nz=8 y blockSize=10m ignorando depth/escala -> grilla 80m de ancho para cualquier dominio (incluido regional)**
- file: terraquantum-web\lib\terraquantum\geophysicsModel.ts:122-138
- impacto: nx=nz=8 con blockSize=10 produce un dominio horizontal FIJO de 80m x 80m sin importar la escala. Para un survey regional de 157km esto es absurdo (8 celdas de 10m). El payload que se envia al backend (buildGeophysicsPayload) propaga esta grilla minuscula. Contradice directamente los parametros de la memoria CORE-REAL-9 (blockSize=1552m, nx=32, ny=20, nz=32). O este builder esta muerto o esta cableado a la escala demo y rompe la escala regional citada en el 'Bug de Bushveld'.
- fix: Derivar nx/nz/blockSize de la extension real del survey (bounding box de observations) y la escala; no cablear 8x8x10.
- VERIFICACION: incierto (sev->) :: verificacion fallo
### [P2] parseObservations-throws-uncaught-01 | dim:3 (robustez, respuestas no-JSON)  | conf:media
**parseObservations hace JSON.parse y throw sin captura en el punto de uso visible; CSV/JSON malformado puede burbujear como excepcion no-JSON**
- file: terraquantum-web\lib\terraquantum\geophysicsSurvey.ts:52-85
- impacto: JSON.parse sobre input de usuario lanza SyntaxError crudo (no el Error de dominio) si el texto esta malformado. countObservations:88 lo envuelve en try/catch y devuelve 'invalido', pero parseObservations en si propaga. Si algun caller (payload submit) no envuelve, un survey malformado revienta el flujo. El minimo de 10 observaciones es una regla de negocio cableada en el cliente que puede no coincidir con el backend.
- fix: Capturar SyntaxError y relanzar un Error de dominio uniforme; centralizar validacion con el backend.
### [P2] is-active-density-null-conflation-01 | dim:1 (condicion sobre-amplia) + 8 (oculta dato real) | conf:media
**Filtro de visibilidad descarta voxel si density===null O rho===null, ocultando celdas con susceptibilidad valida en modo susceptibility**
- file: terraquantum-web\lib\terraQuantumGeology.ts:419
- impacto: En viewMode='susceptibility', un voxel de una corrida magnetica-only podria traer density=null/rho=null pero susceptibility_si valido. La guardia lo descarta ANTES de evaluar susceptibilidad, ocultando el cuerpo magnetico real. El filtro de actividad esta acoplado a densidad aunque la capa activa sea susceptibilidad. El cuerpo real magnetico desaparece.
- fix: La condicion de descarte por null debe depender de la capa activa: en modo susceptibility validar susceptibility_si, no density/rho.
### [P3] envelope-uses-different-filters-01 | dim:1 (inconsistencia de filtros)  | conf:media
**AnomalyEnvelope filtra por minTargetScore/minAnomalyIntensity/minDensityAnomalyScore pero NO por DOI/slice/professionalMode, asi que la envolvente puede englobar voxeles ocultos**
- file: terraquantum-web\componentes\Scene3D.tsx:433-447
- impacto: El comentario dice 'Honour the same user filters as the voxel renderer' pero NO honra DOI (sensitivity<0.05), slice half-space, ni el umbral profesional. La esfera/envolvente puede dibujarse alrededor de voxeles que el renderer oculta, sugiriendo un cuerpo mas grande del que realmente se muestra. Engana sobre la extension del target.
- fix: Aplicar exactamente el mismo conjunto de filtros (incluyendo DOI, slice y professional threshold) que updateInstancedBuffers, o derivar la envolvente de los voxeles realmente visibles.
### [P3] worker-import-meta-url-nextjs-01 | dim:3 (robustez) + 6 (escalabilidad) | conf:baja
**Worker instanciado via new Worker(new URL(... import.meta.url)) sin verificar soporte del bundler Next custom (AGENTS.md advierte que no es el Next conocido)**
- file: terraquantum-web\componentes\Scene3D.tsx:611-615
- impacto: Si la creacion del worker falla (bundler no transpila el worker TS, navegador sin soporte, CSP), workerRef queda null y para modelos >50k el path sincrono ya hizo fill(0): malla vacia permanente sin error visible. AGENTS.md advierte explicitamente que este Next.js tiene breaking changes y no es el conocido. No hay deteccion de fallo de worker.
- fix: try/catch en creacion del worker; si falla, degradar al path sincrono (aunque bloquee) o mostrar error, nunca dejar la escena vacia en silencio.