# DIGEST LOTE2
TOTAL: {'P0': 9, 'P1': 30, 'P2': 32, 'P3': 30}

## Cliente API frontend (frontendApi.ts + app/api/_lib/backend.ts)  (P0:1 P1:4 P2:3 P3:3) archivos:5
### [P0] F1 | conf:alta
**getF32/getI32 devuelven arrays de CEROS si falta la columna: fabrica un modelo fisico degenerado (density=0) sin avisar**
- file: terraquantum-web/lib/terraquantum/frontendApi.ts:1156-1165, 1171
- impacto: Si el backend cambia el nombre de columna o el parquet no trae 'density', TODO el modelo de bloques se renderiza con density=0 (y x/y/z=0, todos los voxeles colapsados en el origen). El usuario ve un resultado 'valido' (ok:true, status 200) que es fisicamente vacio. densityMin/densityMax caen a 0/1 por el guard de lineas 1292-1293, reforzando la apariencia de normalidad. Pecado capital: enmascara datos faltantes como resultado valido.
- fix: Si una columna requerida (x,y,z,density,probability,ix,iy,iz) no esta presente, retornar FrontendApiResult con ok:false y error explicito en lugar de Float32Array(n) de ceros. hasCol() ya existe; usarlo para validar el set requerido antes de construir cells.
### [P1] F2 | conf:alta
**Frontend recalcula bounds del dominio (domainL/H/W) ignorando los headers autoritativos X-TQ-Bounds del backend: el frontend inventa fisica/escala**
- file: terraquantum-web/lib/terraquantum/frontendApi.ts:1196-1207, 1281
- impacto: El extent del dominio que ve la escena se deriva del subconjunto de voxeles devueltos (limitado por 'limit'/select_limited_exploration_view), NO del modelo completo. Con muestreo, domainL/W/H quedan subestimados respecto al dominio fisico real => escala del dominio mal reflejada en el visor. El backend ya tiene la verdad y el FE la descarta y la recalcula. Viola 'el frontend NO debe calcular fisica'.
- fix: Parsear X-TQ-Bounds-Min/Max de los headers y derivar domainL/H/W de ahi (con el centrado/flip-Y que aplica el backend), en vez de recomputar desde el subconjunto devuelto.
### [P1] F3 | conf:alta
**_inferCellSizeFromFloat32 inventa el tamano de celda en TypeScript con un default magico de 10 m**
- file: terraquantum-web/lib/terraquantum/frontendApi.ts:1125-1137, 1207
- impacto: El tamano de celda es un parametro fisico del modelo de inversion (blockSize). Re-inferirlo desde coordenadas redondeadas es fragil: si la malla no es regular en X, o todos los X coinciden, devuelve un default silencioso de 10 m, que no tiene relacion con el blockSize industrial (p.ej. 1552 m segun memoria del proyecto). El voxel se dibuja con tamano fisicamente incorrecto sin aviso. El FE inventa fisica que el BE ya conoce.
- fix: El backend debe emitir cell_size en un header (p.ej. X-TQ-Cell-Size) o en el payload; el FE debe consumirlo en vez de heuristica. Eliminar el default 10.
### [P1] F4 | conf:alta
**Errores de gate (regional_scale / spatial_readiness) llegan en respuestas no-2xx y se aplastan a un string generico, perdiendo el payload estructurado de bloqueo**
- file: terraquantum-web/lib/terraquantum/frontendApi.ts:1012-1014, 857-858
- impacto: Cuando el backend bloquea por escala regional o spatial readiness (flujo principal de un proyecto regional como Bushveld), devuelve HTTP no-2xx con un cuerpo estructurado de gate. El FE muestra 'Error 422'/'Error 409' generico en vez de la accion requerida (required_action / acknowledge_regional_scale). En previewGravityCsv el payload de gate se pierde por completo (data:null). El usuario no puede entender ni resolver el bloqueo.
- fix: En !res.ok leer tambien data.error, data.message y required_action; y NO setear data:null cuando el body es el gate estructurado — preservarlo para que la UI lea regional_scale_preflight/blocked_reasons.
### [P1] F5 | conf:media
**fetchInternalJson trata cualquier body vacio como objeto vacio {} y lo marca ok:true en 2xx: respuestas vacias se ven exitosas**
- file: terraquantum-web/lib/terraquantum/frontendApi.ts:464-465, 500-505
- impacto: Un 200/204 con cuerpo vacio (proxy mal configurado, error silencioso del backend que igual devuelve 200) se propaga como exito con data={}. Aguas abajo normalizeBlockModelResponse(({}), mode) producira cells=[], total_voxels=null, returned_voxels=0 — un modelo vacio presentado como valido (ok:true). Combina con el patron de fallback silencioso.
- fix: Para endpoints que deben traer cuerpo, tratar body vacio en 2xx como error de contrato (ok:false). Como minimo no castear {} a T silenciosamente para respuestas que requieren datos.
### [P2] F6 | conf:alta
**elevation_range.min/max_depth_below_surface_m forzados a null en la ruta Arrow aunque el dato exista: contrato de elevacion incompleto segun la ruta**
- file: terraquantum-web/lib/terraquantum/frontendApi.ts:1275-1276
- impacto: El shape de elevacion DIVERGE segun la ruta: por JSON puede traer depth_below_surface, por Arrow (limit>5000) siempre null. La UI que muestre profundidad bajo superficie funcionara con datasets pequenos y se 'apagara' silenciosamente con datasets grandes (contrato que cambia segun ruta).
- fix: Calcular depth = surface_elevation - voxel_elevation en el loop Arrow, o leer columna depth_below_surface_m si el backend la emite, para igualar el shape de ambas rutas.
### [P2] F7 | conf:media
**Default magico densityMin=0 / densityMax=1 cuando los bounds no son finitos: rango fisico inventado**
- file: terraquantum-web/lib/terraquantum/frontendApi.ts:1292-1293
- impacto: Si density viene todo NaN o la columna falto (ver F1, densities=ceros => min=max=0, finitos), el rango de color/escala de densidad cae a [0,1], un rango fisico arbitrario sin unidades reales (g/cm3 o t/m3). Refuerza que un modelo degenerado parezca pintable y normal. Acompana al F1.
- fix: Si densityMin==densityMax o no finitos, marcar el modelo como degenerado (warning/flag) en vez de fabricar [0,1].
### [P2] F8 | conf:alta
**URLs de backend construidas en el cliente con NEXT_PUBLIC_* y fetch directo (deleteRun, fetchProjectFootprint, exportBundleUrl) saltandose el proxy /api; X-TQ-API-Key potencialmente en el bundle**
- file: terraquantum-web/lib/terraquantum/frontendApi.ts:7-10, 702-711, 1065-1078, 695
- impacto: 1) La API key viaja por NEXT_PUBLIC_, por lo que queda embebida en el bundle JS del cliente y es visible para cualquiera (secreto expuesto). 2) Llamadas directas al backend desde el browser exponen la URL/topologia interna y dependen de CORS; el resto del codigo usa el proxy /api (backend.ts con TQ_API_KEY server-side, que es lo correcto). Inconsistencia: unas rutas protegen la key server-side y otras la filtran al cliente.
- fix: Rutear deleteRun/footprint/export por el proxy /api server-side (como block-model) usando TQ_API_KEY (no NEXT_PUBLIC). Nunca poner la API key en una var NEXT_PUBLIC_.
### [P3] F9 | conf:media
**fetchInternalJson usa window.setTimeout/window.clearTimeout y performance/console: rompe en SSR/Edge; ademas finalize llama performance.now sin guard de entorno**
- file: terraquantum-web/lib/terraquantum/frontendApi.ts:446, 523, 423, 1068, 1118
- impacto: Si alguna de estas funciones se invoca en un contexto sin 'window' (RSC, ruta server, prerender), 'window is not defined' lanza. La inconsistencia (algunas guardadas, otras no) indica acoplamiento fragil al cliente. No es showstopper porque hoy se usan client-side, pero es una bomba latente y codigo no-isomorfico.
- fix: Usar setTimeout/clearTimeout globales (sin prefijo window) o un guard isomorfico; evitar performance.now en rutas que puedan ejecutarse server-side.
### [P3] F10 | conf:alta
**Logs de performance [R08]/[QW-6] con console.log en cada fetch del modelo de bloques: ruido y costo en producción, sin flag de entorno**
- file: terraquantum-web/lib/terraquantum/frontendApi.ts:433, 623, 1235-1240, 1319, 1351-1355
- impacto: Cada carga del modelo (potencialmente miles de voxeles, polling) emite logs en consola de cliente en produccion. Menor, pero indica instrumentacion de desarrollo dejada en codigo de release; ensucia consola y consume CPU en construccion de strings aun cuando no se necesita.
- fix: Condicionar a process.env.NODE_ENV !== 'production' o a un flag DEBUG.
### [P3] F11 | conf:baja
**Inconsistencia de timeout entre proxy server (45s) y cliente (120s) puede producir respuesta no-JSON 'aborted' interpretada como error generico**
- file: terraquantum-web/app/api/_lib/backend.ts:4, 41
- impacto: Una inversion legitima que tarde 46-120s seria abortada por el proxy a los 45s y reportada como 'Timeout: el backend tardo mas de 45s', aunque el cliente esperaba 120s. El usuario ve un timeout falso en un calculo que iba a completar. Depende de que las rutas de invert pasen por fetchBackendJson; si /api/geophysics-invert sobreescribe timeoutMs lo mitiga, pero el default global de 45s es riesgoso para inversion.
- fix: Alinear el timeout del proxy server con el del cliente para endpoints de inversion (pasar timeoutMs explicito >=120s en esas rutas), o documentar el contrato de timeouts.

## Rutas BFF Next (app/api/*/route.ts)  (P0:0 P1:3 P2:5 P3:3) archivos:23
### [P1] BFF-01 | conf:alta
**gravity-import/preview hace await res.json() incondicional: enmascara TODO error no-JSON del backend como 'Error interno del proxy' 500**
- file: terraquantum-web/app/api/gravity-import/preview/route.ts:34
- impacto: El bug clasico 'no llega JSON valido' del flujo CSV. Cuando FastAPI cae, devuelve un error page no-JSON, o un gateway responde 502/504, el usuario ve siempre 'Error interno del proxy' con 500, perdiendo el status real (404/422/503) y el cuerpo de error real del backend. El status 422 de validacion CSV (modo estricto) podria llegar bien solo si FastAPI emite JSON; cualquier fallo de infraestructura se reporta mal. Diverge de invert (que usa res.text()+JSON.parse guardado, lineas 86-97) y de _lib/backend.ts (lineas 59-77). Inconsistencia entre rutas hermanas.
- fix: Replicar el patron de invert/route.ts: leer await backendResponse.text(), envolver JSON.parse en try/catch, y si falla devolver { detail: `Error del backend (HTTP ${status})`, raw: text.slice(0,1000) } con el status REAL del backend (no 500). Idealmente usar el helper compartido.
### [P1] BFF-02 | conf:alta
**Inconsistencia de variable de entorno: _lib/backend.ts ignora NEXT_PUBLIC_TERRAQUANTUM_BACKEND_URL (la unica documentada), cayendo al hardcode 127.0.0.1:8010**
- file: terraquantum-web/app/api/_lib/backend.ts:1-2
- impacto: Con la configuracion documentada/por defecto (solo NEXT_PUBLIC_*), TODAS las rutas que usan fetchBackendJson (geophysics-invert, block-model, project-runs, project-run-detail, compare-runs, favorability, geophysics-status, terrain, scenario-*, system-check, backend-health, export-*) ignoran la URL configurada y se conectan siempre al hardcode 127.0.0.1:8010. Solo las 2 rutas de gravity-import respetan NEXT_PUBLIC_*. En cualquier despliegue donde el backend NO este en 127.0.0.1:8010, las rutas BFF apuntan al lugar equivocado mientras gravity-import apunta al correcto: comportamiento divergente e imposible de diagnosticar.
- fix: Unificar: en _lib/backend.ts usar process.env.TERRAQUANTUM_BACKEND_URL || process.env.NEXT_PUBLIC_TERRAQUANTUM_BACKEND_URL || 'http://127.0.0.1:8010', y eliminar el fallback inline en las rutas de gravity-import para que todas usen el helper. Alinear .env.example.
### [P1] BFF-03 | conf:alta
**geophysics-invert: await req.json() sin try/catch en path critico de inversion; body malformado tumba la ruta con 500 sin mensaje util**
- file: terraquantum-web/app/api/geophysics-invert/route.ts:16
- impacto: El endpoint principal de inversion geofisica: si el cliente manda body vacio o JSON malformado, req.json() lanza y Next devuelve un 500 generico sin el mensaje controlado. fetchBackendJson nunca lanza (devuelve result), pero req.json() si. Inconsistente con sus rutas hermanas POST que ya manejan esto. Flujo critico (inversion) sin guarda de entrada.
- fix: Envolver el body = await req.json() en try/catch devolviendo NextResponse.json({ detail: 'Body JSON invalido para inversion geofisica.' }, { status: 400 }), igual que scenario-sweep y sensitivity-sweep.
### [P2] BFF-04 | conf:media
**block-model arrow path: catch no distingue abort (timeout) de otros errores antes de leer 'isTimeout' pero ademas no propaga status del backend en buffer parcial; ademas timeout fijo 90s para descargas grandes**
- file: terraquantum-web/app/api/block-model/route.ts:47-53
- impacto: En errores del path arrow se puede filtrar contenido binario como detail. El timeout de 90s para descarga de un modelo de bloques grande (escala regional) puede abortar transferencias legitimas, devolviendo 504 sobre datos validos. No es enmascaramiento de fisica pero degrada robustez del visor 3D.
- fix: Limitar/normalizar el text de error (validar content-type antes de exponer), y revisar si 90s basta para el tamaño de modelos regionales soportados; considerar streaming en vez de arrayBuffer completo.
### [P2] BFF-05 | conf:media
**gravity-import/preview no valida presencia de 'file' ni que sea File; reenvia FormData potencialmente vacio al backend**
- file: terraquantum-web/app/api/gravity-import/preview/route.ts:12-25
- impacto: Una llamada sin archivo o con campo 'file' no-binario llega al backend que tendra que rechazarla (dependiendo de su robustez), o peor, si el backend tampoco valida, podria producir un preview degenerado. Combinado con BFF-01, el error del backend ante FormData vacio se enmascara como 'Error interno del proxy' 500.
- fix: Validar: if (!(file instanceof File)) return 400 'archivo CSV requerido'. Validar tamaño maximo antes de reenviar.
### [P2] BFF-06 | conf:media
**backend-health devuelve siempre HTTP 200 incluso cuando el backend esta caido (online:false con status 200): un health check que nunca falla a nivel HTTP**
- file: terraquantum-web/app/api/backend-health/route.ts:22-35
- impacto: Cualquier monitor externo o codigo cliente que use el status HTTP (no el campo online del body) creera que el sistema esta sano. Solo el body distingue. Es una decision defendible para un dashboard, pero como 'health endpoint' industrial es enganoso: un uptime monitor lo marcara verde con backend muerto.
- fix: Documentar explicitamente que el consumidor debe leer body.online; o devolver 503 cuando online:false para health checks consumibles por monitores.
### [P2] BFF-07 | conf:media
**system-check considera 'online' por presencia de rutas en openapi.json, no por que funcionen; blockModelReady depende de cells>0 que puede ocultar modelo degenerado**
- file: terraquantum-web/app/api/system-check/route.ts:71-98
- impacto: El panel de sistema reporta READY basandose en la mera existencia de endpoints en el schema OpenAPI, no en su salud funcional. Un backend con la inversion rota pero la ruta registrada se reporta como listo. cells>0 no garantiza un modelo fisicamente valido.
- fix: Distinguir 'ruta registrada' de 'ruta saludable'. Para blockModel, validar tambien domainL/H/W > 0 y returnedCells coherente, no solo cells>0.
### [P3] BFF-08 | conf:alta
**Codigo duplicado: la funcion readBackendMessage/getBackendDetail/asRecord esta clonada en >10 route.ts; riesgo de divergencia y de inconsistencia (detail vs error)**
- file: terraquantum-web/app/api/geophysics-invert/route.ts:4-13
- impacto: Mantenimiento fragil: una correccion al manejo de mensajes de error debe replicarse en ~10 archivos. Las rutas que usan getBackendDetail pierden el campo 'error' del backend que las otras si muestran: mensajes de error inconsistentes segun la ruta.
- fix: Extraer un unico helper readBackendMessage a _lib/backend.ts y consumirlo en todas las rutas; unificar la semantica detail/error.
### [P2] BFF-09 | conf:alta
**export-run/export-report y terrain-texture NO aplican timeout via AbortController; un backend colgado deja el fetch pendiente indefinidamente**
- file: terraquantum-web/app/api/export-run/route.ts:44-51
- impacto: Una exportacion que el backend no completa (deadlock o generacion lenta) deja la ruta BFF colgada hasta el timeout del runtime de Next, sin el 504 controlado que dan las otras rutas. Inconsistencia de robustez en paths de descarga.
- fix: Aplicar AbortController con setTimeout (p.ej. 60-120s) en export-run y export-report, devolviendo 504 en abort, como hace el path arrow de block-model.
### [P3] BFF-10 | conf:media
**terrain devuelve status 200 forzado en exito aunque el backend respondiera otro 2xx; minor mismatch de status**
- file: terraquantum-web/app/api/terrain/route.ts:40
- impacto: Menor. Inconsistencia de contrato: el cliente no ve el status real 2xx del backend para terrain. No rompe el flujo comun.
- fix: Usar { status: result.status } por consistencia con las demas rutas.
### [P3] BFF-11 | conf:media
**TQ_API_KEY leida en server side (correcto) pero el header X-TQ-API-Key se omite silenciosamente si la var no esta seteada; backend protegido podria recibir requests sin clave y la ruta no lo advierte**
- file: terraquantum-web/app/api/_lib/backend.ts:46-54
- impacto: No es exposicion de secreto (la key se mantiene server-side, bien). Pero el fallback silencioso a 'sin auth' significa que un despliegue mal configurado (olvido de TQ_API_KEY) enviara requests sin autenticar; si el backend exige la key respondera 401/403 y, por BFF-01 en preview, podria enmascararse. No hay warning de configuracion.
- fix: Opcional: loguear una advertencia en arranque si TQ_API_KEY no esta presente en produccion. Mantener la key fuera de NEXT_PUBLIC_ (ya correcto).

## Panel de preview CSV (GravityCsvPreviewPanel)  (P0:1 P1:3 P2:5 P3:3) archivos:5
### [P0] CSV-P0-01 | conf:alta
**El Bounding Box (4 esquinas) se valida pero solo se envian 2 esquinas como anchor lat/lon; fallback silencioso a coordenadas hardcoded de Chile**
- file: terraquantum-web/componentes/GravityCsvPreviewPanel.tsx:584-585
- impacto: Dos defectos en uno: (1) De las 4 coordenadas exigidas al usuario solo 2 viajan; el centro real del survey queda mal anclado (se usa la esquina NO en vez del centroide), desplazando la georreferenciacion del modelo. (2) Si el usuario deja los campos vacios (que la UI permite: 'Opcional'), se inyectan silenciosamente coordenadas de Calama/norte de Chile (-22.28, -68.89). Un CSV de cualquier otra parte del mundo se georreferencia en Chile sin ningun aviso, fingiendo una ubicacion fisica valida. El badge de georef y el footprint resultante mienten sobre donde esta la anomalia.
- fix: Enviar el bounding box completo al backend y que este derive el centroide; mientras tanto, calcular lat/lon como punto medio ((latNorth+latSouth)/2, (lonEast+lonWest)/2) y NUNCA usar fallback geografico hardcoded: si faltan coords, mandar el modelo como LOCAL/sin georref en vez de fabricar una ubicacion.
### [P1] CSV-P1-01 | conf:alta
**Error 422 GEOPHYSICS_INPUT_VALIDATION del backend se degrada a mensaje generico 'Error 422' (detail es objeto, no string)**
- file: terraquantum-web/lib/terraquantum/frontendApi.ts:1012-1014
- impacto: Cuando la inversion falla por validacion de input (caso comun: malla degenerada, parametros invalidos derivados del CSV), el usuario solo ve 'Error 422' sin el message del backend que explica que arreglar. La causa raiz queda oculta. Mismo problema con la rama 422 GEOPHYSICS_INPUT_VALIDATION (linea 842) que tampoco se mapea en handleInvert.
- fix: En handleInvert agregar ramas para detail.error === 'GEOPHYSICS_INPUT_VALIDATION' y leer detail.message; en frontendApi extraer tambien detail.message cuando detail es objeto.
### [P1] CSV-P1-02 | conf:media
**Validacion cliente de UTM diverge del backend: solo se exige hemisferio N/S en FE, pero deriva EPSG que el backend puede recalcular distinto**
- file: terraquantum-web/componentes/GravityCsvPreviewPanel.tsx:40-58
- impacto: Logica de derivacion EPSG duplicada en TS y Python (viola regla del proyecto: 'NO duplicar logica de Python en TypeScript'). El EPSG mostrado al usuario (EPSG:32719 etc.) se calcula en el cliente y puede no coincidir con el que el backend realmente aplica si las reglas divergen, dando una etiqueta de CRS enganosa.
- fix: El FE no debe derivar EPSG; debe mostrar el epsg_code que retorna el backend en georef_preview/georef. Eliminar deriveEpsgFromUtmZone como fuente de verdad mostrada al usuario.
### [P1] CSV-P1-03 | conf:alta
**Preview con status 'ok' pero 0 observaciones validas se muestra como exito; tabla de preview vacia no bloquea ni advierte**
- file: terraquantum-web/componentes/GravityCsvPreviewPanel.tsx:1222-1247
- impacto: Un CSV que el backend acepta estructuralmente pero del que extrae 0 observaciones utiles aparece como validacion exitosa (badge verde). El usuario procede a invertir sobre un dataset vacio/degenerado creyendo que esta OK. Es el 'pecado capital': estado degenerado presentado como valido.
- fix: Si status==='ok' pero valid_rows===0 o totalObservations===0, mostrar un estado de advertencia/error explicito y deshabilitar el boton de inversion.
### [P2] CSV-P2-01 | conf:media
**obs.g.toExponential() sin guarda de tipo; tipo declara g:number obligatorio pero el backend podria omitirlo/enviar null**
- file: terraquantum-web/componentes/GravityCsvPreviewPanel.tsx:1302
- impacto: Un solo punto de observacion con g faltante o no numerico crashea el render del panel completo (pantalla en blanco / React error). El optimismo del tipo TS no protege en runtime contra payloads reales.
- fix: Usar guarda: typeof obs.g === 'number' && Number.isFinite(obs.g) ? obs.g.toExponential(4) : '—'. Reusar fmtSci de datos/helpers.ts que ya hace exactamente esto.
### [P2] CSV-P2-02 | conf:media
**previewLimit acepta NaN (input vaciado) y se envia literal 'NaN' al backend; no hay clamp a min/max declarados**
- file: terraquantum-web/componentes/GravityCsvPreviewPanel.tsx:1170
- impacto: Se envia un preview_limit invalido ('NaN' o 0) al backend, que puede fallar el parseo o devolver 0 filas, contribuyendo al falso 'OK vacio'. Es contrato roto silencioso.
- fix: Clampear: setPreviewLimit(Math.min(100, Math.max(1, Math.floor(Number(e.target.value)) || 1))).
### [P2] CSV-P2-03 | conf:alta
**Control 'CSV Magnetometria' es un control fantasma: acepta archivo pero no lo procesa ni valida ni envia**
- file: terraquantum-web/componentes/GravityCsvPreviewPanel.tsx:427-432
- impacto: El usuario puede subir un CSV de magnetometria creyendo que se procesara (la UI lo presenta junto a gravimetria como entrada de primera clase). El archivo se ignora por completo. Promete una capacidad inexistente (joint/magnetic) — enganoso para un sistema que se anuncia como gravimetrico/magnetico.
- fix: Ocultar/deshabilitar el input con etiqueta 'Proximamente' o cablearlo realmente al endpoint correspondiente.
### [P2] CSV-P2-04 | conf:media
**handleValidate no captura excepciones de previewGravityCsv: si la promesa rechaza, loading queda en true para siempre**
- file: terraquantum-web/componentes/GravityCsvPreviewPanel.tsx:445-462
- impacto: Estado de carga colgado sin recuperacion para el usuario; requiere recargar la pagina. Path critico (boton principal) sin red de seguridad.
- fix: Envolver el cuerpo de handleValidate/handleInvert en try/finally con setLoading(false) en finally.
### [P2] CSV-P2-05 | conf:media
**handleInvert: tras setInvertResult(res.data), si !res.data se intenta setear error pero res.data ya fue consumido como valido; rama muerta/incoherente**
- file: terraquantum-web/componentes/GravityCsvPreviewPanel.tsx:630-656
- impacto: Logica de guarda en orden incorrecto: el caso de respuesta vacia ya escribio invertResult=null en el store y el render aguas abajo puede comportarse de forma inconsistente antes del return. Indica que la validacion de contrato no esta antes del uso.
- fix: Mover el check if (!res.data) inmediatamente despues de comprobar res.ok, ANTES de setInvertResult y de leer res.data.georef.
### [P3] CSV-P3-01 | conf:alta
**LEGACY_INVERSION_PARAMS (nx/ny/nz/blockSize/depth) se siguen enviando aunque el backend los ignora; engano de configurabilidad**
- file: terraquantum-web/componentes/GravityCsvPreviewPanel.tsx:126
- impacto: Contrato inflado con parametros que no tienen efecto; cualquier mantenedor futuro asume que nx/ny/nz controlan la malla cuando no. Riesgo de confusion y de regresion si alguien intenta 'arreglar' la malla cambiando estos valores.
- fix: Marcar estos campos como deprecados en el schema o dejar de exigirlos en el endpoint; documentar que la malla es auto-derivada.
### [P3] CSV-P3-02 | conf:media
**Logica de georef triplicada/divergente: getGeorefBadge vs getGeorefBadgeLabel/Class/Explanation usan claves de confianza distintas**
- file: terraquantum-web/componentes/GravityCsvPreviewPanel.tsx:84-114
- impacto: El mismo CSV puede mostrar 'Georreferenciacion ALTA' por una via y 'BAJA' por otra dependiendo de si el backend pobla georef_preview o solo coordinate_transform. Etiqueta de confianza inconsistente — critico en interpretacion geologica.
- fix: Unificar en una sola funcion que reciba el confidence canonico del backend; eliminar getGeorefBadge basado en input_coordinate_system.
### [P3] CSV-P3-03 | conf:alta
**buildVoxelModelFromBackend y handleLoadCsvModel3D duplican el ensamblado del BackendVoxelModel con divergencia (uno valida celdas, el otro no)**
- file: terraquantum-web/componentes/GravityCsvPreviewPanel.tsx:699-723
- impacto: Dos caminos para cargar el modelo 3D con validacion distinta; el de handleLoadCsvModel3D puede pasar celdas malformadas al visor 3D. Mantenimiento duplicado y comportamiento inconsistente segun el boton que pulse el usuario.
- fix: handleLoadCsvModel3D debe reutilizar buildVoxelModelFromBackend en vez de reimplementar el parseo.

## DatosView y paneles de run (DatosView.tsx, ProjectRunList.tsx, RunDiagnosticsPanel.tsx, RunFavorabilityPanel.tsx, RunFocusingPanel.tsx)  (P0:3 P1:4 P2:4 P3:2) archivos:11
### [P0] DV-01 | conf:alta
**KPI 'Anomalía profunda' muestra una DENSIDAD (g/cm³) etiquetada como mGal y con default silencioso 2.6**
- file: terraquantum-web/componentes/DatosView.tsx:77-78, 337
- impacto: El primer KPI del panel muestra un numero fisicamente sin sentido (densidad 2.6 g/cm3 rotulada como '+2.6 mGal') que ademas es el valor por defecto que delata una inversion fallida/degenerada. El usuario lo lee como una anomalia real.
- fix: No reutilizar max_density/avg_density como 'anomalia mGal'. Mostrar la anomalia gravimetrica real (g_max/g_min de observationQuality o residual) con su unidad correcta, y bloquear el KPI cuando max_density==avg_density==2.6 / is_demo_grade==true.
### [P0] DV-02 | conf:alta
**Una inversion totalmente fallida (modeled=0, misfit 100%) se renderiza como analisis normal; no se surface ningun flag de fallo**
- file: terraquantum-web/componentes/DatosView.tsx:334-456
- impacto: El pecado capital: un run donde el solver no recupero NADA (modelo nulo, ajuste 100% de error) se presenta como un analisis de inversion completo y aparentemente exitoso. Esto es exactamente 'por que no es industrial': enmascara fallo total del nucleo fisico.
- fix: Leer misfit_error_percent, modeled_max, is_demo_grade, model_reliability_level y priority_class del report; si el modelo es degenerado (modeled_max==0 o misfit>~50% o is_demo_grade) mostrar un banner de fallo y suprimir KPIs/targets/dictamen.
### [P0] DV-03 | conf:alta
**best_target.probability NO es probabilidad (es ranking_score de residual) pero se muestra como 'Score %' al 100% con highlight verde**
- file: terraquantum-web/componentes/DatosView.tsx:47-50, 63, 401-403
- impacto: Presenta un 'target' al 100% de score, resaltado como excelente, a 286 km de profundidad y con densidad por defecto, derivado de un campo que explicitamente NO es probabilidad. Induce a creer que hay un blanco de perforacion de altisima confianza donde no hay nada.
- fix: Renombrar la metrica a 'score relativo de ranking' (no %/probabilidad), no aplicar highlight de 'excelente', y gate por profundidad/reliability. No usar el campo 'probability' como porcentaje de confianza.
### [P1] DV-04 | conf:alta
**El 'estado' del target se llena con recommendation/drill_recommendation, pero el render compara contra priority_class -> color/etiqueta siempre erradas**
- file: terraquantum-web/componentes/DatosView.tsx:113-116, 373-393
- impacto: La clasificacion/coloreo del unico target mostrado nunca refleja el priority_class real del backend; un UNCLASSIFIED se muestra con etiqueta/color arbitrario. Control de prioridad fantasma.
- fix: Poblar estado desde persistedReport.priority_class (y best_target/spatial_readiness_cap), no desde recommendation. Alinear las constantes comparadas con los valores reales del backend.
### [P1] DV-05 | conf:alta
**Stale report: al cambiar de run activo no se limpia 'report'; el effect hace 'if (report) return' y deja KPIs del run anterior bajo el nuevo header**
- file: terraquantum-web/componentes/DatosView.tsx:188-189
- impacto: DatosView muestra los KPIs, ranking de targets, dictamen y region del run anterior mientras el header (RunHeader/Run ID) y los metadatos muestran el run nuevo. Resultado fisico de una corrida atribuido a otra.
- fix: Limpiar report al cambiar projectId/runId (setReport(null) en setActiveRun o en clearActiveRun, o quitar la guarda 'if (report) return' y depender de un key por runId).
### [P1] DV-06 | conf:alta
**report.score mezcla fit_quality y observationQuality.quality_score en un mismo % de 'Confianza' sin distinguir real vs estimado**
- file: terraquantum-web/componentes/DatosView.tsx:103-105, 441
- impacto: Una corrida con ajuste pesimo puede mostrar 'Confianza 100%' solo porque la cobertura de sensores era buena. El usuario no puede saber cual de las dos cosas esta viendo.
- fix: No colapsar dos metricas en un solo 'Confianza'. Mostrar fit_quality y quality_score por separado con etiqueta clara; nunca usar quality_score del survey como confianza del modelo.
### [P1] DV-07 | conf:alta
**QA/QC, L-curve y diagnosticos se muestran sin distinguir 'no disponible' de 'valor 0/degenerado'; quality_score GOOD junto a fit LOW**
- file: terraquantum-web/componentes/datos/RunDiagnosticsPanel.tsx:329-401
- impacto: El usuario ve un badge verde 'GOOD' prominente (calidad de observaciones) que contradice el ajuste nulo del modelo; refuerza la falsa sensacion de resultado valido.
- fix: Cruzar fit/modeled con QA: si modeled_max==0 o misfit alto, degradar visualmente el bloque QA y mostrar advertencia 'modelo no recuperado'. Distinguir explicitamente metrica ausente de metrica=0.
### [P2] DV-08 | conf:media
**ProjectRunList genera valores de barrido fisico (lambda/alpha) en TypeScript multiplicando inputs**
- file: terraquantum-web/componentes/datos/ProjectRunList.tsx:250-251
- impacto: Aunque el computo lo hace el backend, la eleccion de los puntos de muestreo de regularizacion (decision metodologica de la inversion) vive en el cliente, violando la regla 'la fisica/regularizacion ocurre solo en el backend' y haciendo el resultado dependiente de logica TS duplicable/divergente.
- fix: Que el endpoint del sweep reciba solo el run y genere internamente la grilla de lambda/alpha (o reciba un 'profile' nombrado), no factores 0.5x/2x hardcodeados en el frontend.
### [P2] DV-09 | conf:media
**Sensibilidad: payload del sweep reenvia todas las observations desde el cliente (copia grande) y depende de inputs que pueden faltar**
- file: terraquantum-web/componentes/datos/ProjectRunList.tsx:218-253
- impacto: Reenvio de cientos/miles de observaciones por la red para algo que el backend ya tiene en disco; y si el detalle no incluye observations el boton 'Ejecutar sweep' falla con 'No hay inputs/observations suficientes' aunque el run si las tenga persistidas.
- fix: Que el backend lea observations/inputs del run por project_id/run_id; el frontend solo manda identificadores y la grilla (o profile). Validar shape de inputs antes de enviar.
### [P2] DV-10 | conf:media
**RunFavorabilityPanel asume scoring_detail y gates siempre presentes (sin optional chaining); response degradada rompe el render**
- file: terraquantum-web/componentes/datos/RunFavorabilityPanel.tsx:94, 122-130, 144-146, 187-190
- impacto: Una favorability con shape parcial (campo opcional faltante) rompe el panel en runtime en lugar de degradar. La barra de factores usa value*100 asumiendo 0-1 cuando los valores no estan homogeneamente normalizados.
- fix: Validar/parsear FavorabilityResult con defaults y optional chaining antes de render; tratar campos opcionales como opcionales; no asumir que factor.value es 0-1 para la barra.
### [P2] DV-11 | conf:alta
**Volumen anomalo y masa muestran 0 Ton silenciosamente cuando tonnage es null (default enmascarado)**
- file: terraquantum-web/componentes/DatosView.tsx:65-67, 339
- impacto: Un dato ausente (tonelaje no estimable, is_demo_grade) se presenta como '0.0 Ton' calculado, indistinguible de un volumen realmente cero. Ademas divide entre 1000 una masa ya nula sin clarificar unidades (kg->Ton sobre un campo llamado tonnage).
- fix: Mostrar 'N/D' cuando tonnage es null en vez de 0; aclarar unidad real del campo de origen.
### [P3] DV-12 | conf:alta
**Exportar PDF: control que solo dispara window.print() tras setTimeout fijo de 1200ms, sin generar PDF ni manejar fallo**
- file: terraquantum-web/componentes/DatosView.tsx:264-267
- impacto: El boton 'Exportar PDF' (variant primary, destacado) no exporta PDF: abre el dialogo de impresion del navegador tras un delay arbitrario. El estado 'Generando…' es cosmetico. No es exportacion real reproducible.
- fix: O bien renombrar a 'Imprimir', o implementar exportacion PDF real vinculada al endpoint de reporte. Quitar el setTimeout arbitrario.
### [P3] DV-13 | conf:media
**RunHeader muestra solo runId; el run cargado desde modelo 3D no trae projectId/region/report y la cabecera no lo refleja**
- file: terraquantum-web/componentes/DatosView.tsx:484-497, 552-554
- impacto: Inconsistencia de informacion segun la ruta de carga (Historial vs 'Cargar modelo 3D'): mismo run muestra distinta cantidad de metadatos. Region 'Desconocida' como default silencioso.
- fix: Unificar el shape de activeRun en ambas rutas de carga o indicar explicitamente que faltan metadatos en lugar de omitir secciones.

## Estado global Zustand (useAppStore.ts + qaStatus.ts)  (P0:0 P1:2 P2:3 P3:3) archivos:6
### [P1] ZUS-01 | conf:alta
**Subsistema de polling del worker de inversion asincrona es codigo muerto completo: el progreso nunca se muestra al usuario**
- file: terraquantum-web/store/useAppStore.ts:345-358, 660-686
- impacto: La inversion gravimetrica/magnetica es una operacion larga (worker async). Toda la maquinaria de estado para reportar etapa/progreso/heartbeat existe pero esta desconectada: el usuario nunca ve progreso ni etapa de la inversion. Un proceso que tarda minutos aparece congelado.
- fix: O cablear el loop de polling real (fetch al status_url del job, setPollingState en cada tick, resetPollingState al terminar) y consumir pollingProgress en la UI, o eliminar toda la seccion 12 del store si el progreso se maneja por otra via.
### [P2] ZUS-02 | conf:alta
**pollingRef en Exploration3DView arma cleanup de un setTimeout que nunca se crea (mecanismo de polling esqueleto)**
- file: terraquantum-web/componentes/views/Exploration3DView.tsx:240-254
- impacto: Aparenta un loop de polling con cleanup correcto, pero es un esqueleto sin cuerpo. El cleanup limpia siempre undefined. Refuerza la falsa impresion de que la inversion async tiene seguimiento.
- fix: Implementar el loop (asignar pollingRef.current.timeoutId = setTimeout(tick,...) y active=true al iniciar) o eliminar pollingRef y su effect.
### [P1] ZUS-03 | conf:alta
**susceptibilityDataAvailable arranca en true y solo se corrige en modo susceptibility: banner de 'datos no disponibles' tardio y estado stale entre corridas**
- file: terraquantum-web/store/useAppStore.ts:515, 419-444
- impacto: Una corrida solo-gravimetrica puede mostrarse en modo susceptibilidad SIN el banner de advertencia (default true, solo se corrige despues de que el render effect corra en ese modo), pintando voxeles grises neutros como si fueran susceptibilidad valida. Es el pecado capital: un default positivo (true) enmascara datos faltantes.
- fix: Inicializar susceptibilityDataAvailable en false y/o resetearlo en setModel y clearActiveRun. Calcular disponibilidad al cargar el modelo (no solo dentro de viewMode==='susceptibility'), reutilizando classifyViewModeAvailability('susceptibility', cells).
### [P2] ZUS-04 | conf:alta
**clearActiveRun no resetea estado de render/multifisica/loading: estado stale tras cambiar de corrida o proyecto**
- file: terraquantum-web/store/useAppStore.ts:388-414
- impacto: Al limpiar la corrida activa, el visor 3D arranca la siguiente en un viewMode heredado (p.ej. 'joint' de una corrida conjunta previa) sobre un modelo gravity-only, o con isWorkerProcessing/isBlockModelLoading colgados en true mostrando overlays de carga fantasma. Reduce reproducibilidad.
- fix: Extender clearActiveRun para resetear viewMode a 'density', susceptibilityDataAvailable a su default, isWorkerProcessing/isBlockModelLoading a false, contadores de voxeles a null, selectedVoxel a null y la seccion polling (o llamar resetPollingState).
### [P2] ZUS-05 | conf:media
**El gate QA de viewMode es decorativo: handleSetViewMode ignora FAIL y cambia de modo igual (control que no protege)**
- file: terraquantum-web/componentes/viewport/MultiPhysicsControls.tsx:87-97
- impacto: El usuario puede entrar a un modo fisico sin datos (susceptibilidad/joint en corrida gravity-only). El gate QA da falsa sensacion de proteccion: la semantica FAIL no impide la accion, solo pinta un badge.
- fix: Si la intencion es no bloquear, renombrar el estado a WARN en vez de FAIL para no implicar gating. Si debe proteger, hacer que handleSetViewMode retorne temprano (no llamar setViewMode) cuando qa.status === 'FAIL', mostrando el motivo al usuario.
### [P3] ZUS-06 | conf:media
**classifyViewModeAvailability('susceptibility') marca NO-disponible cualquier modelo con susceptibilidad identicamente cero (base_susc=0)**
- file: terraquantum-web/lib/terraquantum/qaStatus.ts:139-151
- impacto: Confunde un modelo magnetico degenerado (todo chi=0, que SI deberia alertarse como solver-failed) con 'no es magnetico'. El razon mostrado al usuario es enganoso. Menor porque normalmente al menos una celda tendra chi!=0.
- fix: Distinguir tres casos: campo ausente (NOT_AVAILABLE), campo presente pero todo cero (FAIL 'sin contraste / solver degenerado'), y campo con valores no-cero (PASS). No mezclar 'ausente' con 'todo cero' bajo el mismo mensaje 'solo gravimetrica'.
### [P3] ZUS-07 | conf:alta
**setModel ejecuta performance.now() y console.log de telemetria en cada cambio de modelo dentro del setter del store**
- file: terraquantum-web/store/useAppStore.ts:420, 443
- impacto: console.log en cada carga de modelo (cientos de miles de celdas) ensucia la consola en produccion y agrega overhead menor. Telemetria [R08] de desarrollo filtrada al bundle cliente.
- fix: Guardar el log tras un flag de debug (process.env.NODE_ENV === 'development') o eliminarlo.
### [P3] ZUS-08 | conf:media
**El recalculo de jointThreshold reconstruye toda la geometria del InstancedMesh (slider costoso)**
- file: terraquantum-web/componentes/Scene3D.tsx:859-888, 989-998
- impacto: Mover el slider jointThreshold reejecuta el effect de construccion de buffers de TODO el InstancedMesh en cada onChange, no solo un filtro de visibilidad GPU. En modelos grandes esto es costoso y puede congelar la UI durante el arrastre.
- fix: Aplicar el filtro de jointThreshold como uniform/visibilidad por instancia sin reconstruir buffers, o debouncing del slider, o separar el recalculo de color del de geometria.

## Vistas principales (terraquantum-web/componentes/views): HomeView, HistorialView, IAChatView, Exploration3DView  (P0:3 P1:4 P2:3 P3:5) archivos:8
### [P0] TQ-VIEWS-001 | conf:alta
**IAChatView apunta a URL/puerto hardcodeado equivocado (localhost:8000) ignorando BACKEND_PUBLIC_URL (127.0.0.1:8010) -> el chat nunca conecta**
- file: terraquantum-web/componentes/views/IAChatView.tsx:36
- impacto: El unico flujo de la vista IAChatView (mandar mensaje a la IA) falla con error de red en cualquier despliegue donde el backend no este casualmente en localhost:8000. El usuario solo ve 'Error de conexion con la IA'. Flujo principal de la vista roto. Ademas, URL hardcodeada = imposible cambiar por entorno (dev/stage/prod).
- fix: Usar BACKEND_PUBLIC_URL (o una funcion del frontendApi) en lugar de la cadena literal; idealmente mover el fetch del chat a frontendApi.ts como el resto de endpoints.
### [P0] TQ-VIEWS-002 | conf:alta
**IAChatView no envia X-TQ-API-Key: con TQ_AUTH_ENABLED=true el backend responde 401 a TODO el chat**
- file: terraquantum-web/componentes/views/IAChatView.tsx:36-44
- impacto: Cuando la autenticacion esta activada (produccion), el chat geologico siempre devuelve 401. El frontend lo mapea a 'Error en la respuesta del servidor' (line 47) -> burbuja 'Error de conexion con la IA'. La feature esta muerta en cualquier entorno seguro.
- fix: Anadir el header X-TQ-API-Key al fetch (o rutear via el wrapper de frontendApi que ya lo gestiona) y NO depender de un secreto en cliente (ver TQ-VIEWS-003).
### [P0] TQ-VIEWS-003 | conf:alta
**HistorialView/deleteRun usa NEXT_PUBLIC_TQ_API_KEY: clave de API del backend embebida en el bundle del cliente (secreto expuesto)**
- file: terraquantum-web/lib/terraquantum/frontendApi.ts:703-709
- impacto: La clave que protege DELETE de corridas (y por extension toda la API) viaja en el bundle del cliente, visible en DevTools/source maps. Un atacante la extrae y obtiene acceso completo de escritura/borrado al backend. Borrado irreversible de modelos (HistorialView lo describe: 'eliminará el modelo y todos los archivos asociados... No se puede deshacer').
- fix: Nunca exponer la clave en cliente. Proxyar las mutaciones por una route handler de Next.js (server-side) que adjunte la clave desde una env var NO publica, o usar sesion/cookie httpOnly. Renombrar la env a TQ_API_KEY (sin NEXT_PUBLIC_).
### [P1] TQ-VIEWS-004 | conf:alta
**Filtro de compliance JORC/NI-43-101 es ineficaz: matchea palabras en INGLES sobre un asistente que responde en ESPANOL**
- file: terraquantum-backend/api/chat_api.py:12-24
- impacto: El guardrail de cumplimiento (vendido como compliance JORC/NI-43-101) no bloquea las violaciones reales en el idioma que el modelo usa. Riesgo regulatorio: el asistente puede emitir estimaciones de recursos/ley/tonelaje sin redactarse. Ademas substring crea falsos positivos: 'grade' matchea 'upgrade'/'degrade', 'reserve' matchea 'reservorio'/'reserved' -> redacta texto legitimo. El filtro es ademas todo-o-nada: una sola palabra borra la respuesta completa.
- fix: Filtrar por terminos en el idioma de salida (espanol) con limites de palabra (regex \b), o mejor mover el guardrail a clasificacion semantica; no usar substring. Idealmente redactar solo el fragmento, no toda la respuesta.
### [P1] TQ-VIEWS-005 | conf:media
**IAChatView siembra historial con role:'model' como primer mensaje -> historial de Gemini empieza en 'model', viola precondicion (history debe iniciar en user)**
- file: terraquantum-web/componentes/views/IAChatView.tsx:11-16, 30-43
- impacto: El primer turno real del usuario puede fallar en el backend (HTTPException 500 'Error en la IA: ...') porque el history pasado a start_chat empieza con role model. El usuario ve 'Error de conexion'. Acopla un detalle de UI (saludo precargado) con el contrato del LLM.
- fix: No incluir el saludo seedeado en el payload al backend (filtrar el primer mensaje 'model' o no enviarlo), o que el backend descarte mensajes 'model' iniciales antes de construir el history.
### [P1] TQ-VIEWS-006 | conf:alta
**IAChatView: 'Confidence' y 'Masa Estimada' usan `valor || "N/A"` -> un 0 fisico real (modelo degenerado/vacio) se enmascara como 'N/A'**
- file: terraquantum-web/componentes/views/IAChatView.tsx:109, 114
- impacto: Un resultado fisicamente valido pero nulo (confianza 0, masa 0) se presenta como 'dato no disponible', indistinguible de 'no hay modelo'. El usuario no distingue 'modelo dice 0' de 'no se calculo'. Clasico fallback que finge ausencia de resultado. Ademas 'Confidence' muestra el score crudo (p.ej. 0.42) sin formato ni % (a diferencia de DatosView.tsx:441 que hace score*100 .toFixed(0)+'%').
- fix: Usar checks por nullish/Number.isFinite (report.score != null && Number.isFinite(report.score)) y formatear consistentemente (score*100 %). No usar || sobre numericos que pueden ser 0.
### [P1] TQ-VIEWS-007 | conf:media
**IAChatView muestra 'Masa Estimada ... kg' pero el campo masaKg es realmente VOLUMEN/tonelaje (mismo campo etiquetado 'Volumen anomalo' en DatosView): etiqueta fisica enganosa**
- file: terraquantum-web/componentes/views/IAChatView.tsx:107-110
- impacto: La vista de chat presenta como 'Masa Estimada (kg)' una cifra que el resto del sistema trata como tonelaje/volumen anomalo. Numero fisico mal etiquetado y unidades inconsistentes entre vistas (divergencia de logica clonada). Riesgo de interpretacion erronea por el usuario tecnico y contradiccion directa con el guardrail anti-tonelaje del propio chat.
- fix: Unificar la semantica/unidad del campo en un solo lugar (store/tipos) y etiquetarlo igual en todas las vistas; clarificar si es masa, tonelaje o volumen. Evitar mostrar tonelaje en la vista cuyo backend prohibe 'tonnage'.
### [P2] TQ-VIEWS-008 | conf:alta
**IAChatView siempre muestra estado 'Online' (badge verde pulsante) sin comprobar el backend; sugiere disponibilidad falsa**
- file: terraquantum-web/componentes/views/IAChatView.tsx:138-141
- impacto: UI muestra 'Online' aunque cada envio falle. El usuario confia en un indicador que no refleja el estado real de conexion con la IA. Estado de error presentado como UI normal.
- fix: Derivar el badge de un estado real (ultimo fetch ok / healthcheck) o eliminarlo.
### [P3] TQ-VIEWS-009 | conf:alta
**IAChatView: render del error usa `${error}` interpolando el objeto Error completo (mensaje de fallo crudo en la burbuja)**
- file: terraquantum-web/componentes/views/IAChatView.tsx:52-56
- impacto: Mensajes de error tecnicos crudos en la conversacion del usuario; y si la respuesta JSON no trae 'response', la burbuja queda con 'undefined' sin aviso. Manejo de error/JSON poco robusto en el path principal de la vista.
- fix: Normalizar el mensaje de error (error instanceof Error ? error.message : 'fallo') y validar que data.response sea string antes de renderizar.
### [P2] TQ-VIEWS-010 | conf:media
**Exploration3DView: viewMode/viewModeLabel solo etiqueta el overlay; el cambio de objeto fisico (densidad/susceptibilidad/joint) no recarga el modelo desde backend**
- file: terraquantum-web/componentes/views/Exploration3DView.tsx:275-285, 367-455
- impacto: El control multi-fisica puede dar la impresion de cambiar el objeto fisico modelado cuando solo cambia la etiqueta/visual; si el coloreo se recalcula de los mismos datos en TS, el frontend estaria reinterpretando fisica en cliente o mostrando susceptibilidad sobre datos de densidad. Posible estado stale entre lo que dice el overlay y los datos cargados.
- fix: Verificar/ligar viewMode a una recarga real del block-model (o documentar que la susceptibilidad viene en el mismo payload). Confirmar que el coloreo no recalcula magnitudes fisicas en cliente (regla de oro del proyecto).
### [P3] TQ-VIEWS-011 | conf:media
**Exploration3DView: useEffect de recarga por modo NO cancela el fetch al desmontar/cambiar deps (sin cleanup); solo se protege con requestId mutable**
- file: terraquantum-web/componentes/views/Exploration3DView.tsx:367-454
- impacto: Cambios rapidos de modo lanzan multiples descargas Arrow (potencialmente 250k voxeles) sin abortar las anteriores -> ancho de banda y CPU desperdiciados; posible flag de loading pegado. No es showstopper pero afecta rendimiento/UX en la vista mas pesada.
- fix: Usar AbortController por effect y cancelar en el cleanup; resetear el loading flag de forma segura ante desmontaje.
### [P3] TQ-VIEWS-012 | conf:alta
**Exploration3DView: getProjectRunDetail importado pero no usado (codigo muerto)**
- file: terraquantum-web/componentes/views/Exploration3DView.tsx:32
- impacto: Import sin uso; ruido/confusion. Menor.
- fix: Eliminar el import no usado.
### [P2] TQ-VIEWS-013 | conf:media
**HistorialView: borrar la corrida activa no limpia georef/elevacion ni reportes -> badges GEOREF/EPSG/DEM quedan stale**
- file: terraquantum-web/componentes/views/HistorialView.tsx:198-204
- impacto: Tras borrar/cambiar de corrida, los metadatos de georreferenciacion/EPSG/DEM del run anterior pueden permanecer en el store y mostrarse en otras vistas (DatosView/HUDs) que no chequean isActive, presentando georef de un modelo que ya no existe. Estado stale no invalidado.
- fix: Limpiar setGeorefState(null/empty) y flags de elevacion al borrar/limpiar la corrida activa.
### [P3] TQ-VIEWS-014 | conf:media
**HistorialView: fetchProjectFootprint(...).then(...).catch(()=>null) traga el error de georef silenciosamente tras cargar modelo**
- file: terraquantum-web/componentes/views/HistorialView.tsx:141-157
- impacto: Si la georref falla al cargar un modelo desde historial, el usuario no recibe aviso y puede ver badges de georref del modelo anterior (stale) o ninguno, sin indicacion de que el footprint no se pudo obtener.
- fix: En la rama no-ok/catch, resetear georefState al neutro y opcionalmente exponer un aviso; al menos console.warn el error.
### [P3] TQ-VIEWS-015 | conf:media
**HomeView: botones de Diseno Mina / Flota FMS navegan sin verificar precondicion de corrida activa (title dice 'Requiere corrida activa')**
- file: terraquantum-web/componentes/views/HomeView.tsx:50-57, 111-125
- impacto: El usuario puede entrar a vistas que requieren una corrida/modelo sin tenerlo; dependera de que la vista destino maneje el estado vacio. El tooltip promete una precondicion que el control no aplica. Menor pero induce a estados sin datos.
- fix: Deshabilitar/condicionar la navegacion segun activeRun, o garantizar manejo de estado vacio en vistas destino.

## Analitica, HUDs, viewport, workspace (terraquantum-web/componentes/{analytics,huds,viewport,workspace})  (P0:0 P1:2 P2:3 P3:6) archivos:24
### [P1] EXEC-REPORT-ZERO-FALLBACK | conf:alta
**ExecutiveGeoReport convierte datos ausentes en ceros/0% presentados como resultados reales**
- file: terraquantum-web/componentes/huds/ExecutiveGeoReport.tsx:6-16, 107-156, 207-239
- impacto: El usuario (o un tercero leyendo el 'Reporte Ejecutivo') ve un informe de aspecto valido y completo aunque el backend no haya calculado nada. Cero densidad/tonelaje/score son fisicamente degenerados pero se presentan con el mismo formato que un resultado real. Es el pecado capital: estado vacio disfrazado de resultado.
- fix: Distinguir null vs 0: que readFirstNumber/readNumberField devuelvan null cuando el campo no existe y renderizar '—'/'Sin datos' en las MetricCard/SmallCard en vez de '0'. No usar `value || 0` para campos fisicos.
### [P1] EXEC-REPORT-DEFAULT-RECOMMENDATION | conf:alta
**Recomendacion de prioridad cae a 'OBSERVE' (Prioridad media) cuando el backend no la entrega**
- file: terraquantum-web/componentes/huds/ExecutiveGeoReport.tsx:100-105
- impacto: Si el backend no produjo ninguna clasificacion de prioridad, la UI inventa 'Prioridad relativa media' como si fuese una decision del modelo. Una recomendacion de perforacion/observacion fabricada en el frontend es exactamente lo que la regla de oro del proyecto prohibe (el FE no debe inventar fisica/decisiones).
- fix: Si las tres claves estan ausentes, mostrar 'Sin clasificar' / '—' (clase UNCLASSIFIED) en lugar de defaultear a OBSERVE.
### [P2] EXEC-REPORT-GRADE-PROXY-USERINPUT | conf:alta
**Density Proxy Index usa como ultimo fallback 'leyEstimada' (supuesto del usuario) en una tarjeta de metrica del modelo**
- file: terraquantum-web/componentes/huds/ExecutiveGeoReport.tsx:126-131, 197-201
- impacto: Si el backend no calcula intensidad de anomalia, la tarjeta muestra el valor que el propio usuario asumio (leyEstimada) como si fuese un indice derivado del modelo gravimetrico. El comentario en codigo lo reconoce explicitamente ('no dato medido del yacimiento') pero igual lo presenta sin marca visual de que es un supuesto.
- fix: No mezclar input del usuario con metricas del modelo en la misma tarjeta; si solo hay leyEstimada, etiquetar 'supuesto usuario' o mostrar '—'.
### [P2] SLICE-THICKNESS-PHANTOM | conf:alta
**sliceThickness es un parametro fantasma: existe en store y se propaga al worker/render pero NUNCA se aplica ni tiene control en la UI**
- file: terraquantum-web/componentes/viewport/SliceControls.tsx:SliceControls.tsx:22-135 (sin UI de thickness); store useAppStore.ts:217-218,507-508; worker voxelBufferBuilder.worker.ts:290-292; terraQuantumGeology.ts:426
- impacto: El sistema dice soportar grosor de seccion (slab) pero solo hace half-space. El parametro viaja por toda la cadena de transporte zero-copy sin efecto. Aunque hoy no hay slider visible, el contrato del worker miente y cualquier futura UI de thickness pareceria funcionar sin hacer nada. Codigo muerto que ensucia el contrato critico de rendimiento.
- fix: O implementar el slab real (visible si |axisPos - slicePosition| <= sliceThickness/2 cuando showOnlySlice) o eliminar sliceThickness del store, worker y geology para no fingir capacidad.
### [P2] NOISE-RESIDUAL-SIGMA-MISLABEL | conf:alta
**Residual sigma cae silenciosamente a residual_rmse y lo presenta como sigma**
- file: terraquantum-web/componentes/analytics/NoiseUncertaintyWidgets.tsx:42, 73
- impacto: RMSE y desviacion estandar del residual son metricas distintas (RMSE incluye el sesgo). Mostrar RMSE etiquetado como σ engaña al usuario tecnico sin ninguna advertencia. Ademas la misma tarjeta 'Residual RMSE' arriba puede mostrar el mismo numero, dando dos cards con valor identico y etiquetas distintas.
- fix: No fusionar residual_std con residual_rmse en numOf; si residual_std no existe, mostrar '—' en la card Residual σ.
### [P3] SNR-COMPUTED-IN-FRONTEND | conf:media
**SNR se calcula en TypeScript (rango dinamico / residual RMSE), fisica derivada en el frontend**
- file: terraquantum-web/componentes/analytics/NoiseUncertaintyWidgets.tsx:44-49, 67-72, 81-84
- impacto: Aunque el texto declara 'indicador de visualizacion, no metrica fisica del backend' (linea 81-84, mitigante honesto), el frontend igualmente deriva y umbraliza un numero con apariencia de SNR fisico, violando la regla de no calcular fisica en TS. El umbral 10/4 es una heuristica inventada en el FE.
- fix: Mover el calculo de SNR y su clasificacion al backend (report.observationQuality.snr) o degradarlo a texto neutro sin tono de calidad good/warn/bad.
### [P3] BACKENDBADGE-RAW-JSON | conf:media
**BackendStatusBadge hace res.json() sin verificar res.ok ni content-type; polling de 8s**
- file: terraquantum-web/componentes/huds/BackendStatusBadge.tsx:55-89
- impacto: Caso menor porque el catch existe y la UI degrada a estado offline; pero un 200 con body no-JSON (raro) tambien lanzaria. El polling cada 8s es continuo mientras el componente este montado (cleanup correcto en unmount), pero re-evalua aun cuando el panel esta colapsado.
- fix: Validar res.ok y content-type antes de json(); considerar pausar el polling cuando !expanded o usar backoff.
### [P3] ANALYTICS-REPORT-SHAPE-DIVERGENCE | conf:media
**Dos consumidores del report usan rutas/shapes distintas (run-detail.report vs store.report.backendReport)**
- file: terraquantum-web/componentes/analytics/AnalyticsPanel.tsx:44-52 (vs ExecutiveGeoReport.tsx:96-98)
- impacto: Para una corrida recien ejecutada (sin run-detail persistido), AnalyticsPanel usa storeReport.backendReport pero busca claves (fitDiagnostics, doiDiagnostics) que viven en otro nivel; si el shape del store no coincide con el de project-run-detail, los widgets cientificos quedan vacios mientras el reporte ejecutivo muestra datos, o viceversa. Acoplamiento fragil entre dos fuentes de verdad para 'el report'.
- fix: Unificar el shape del report en el store con el de getProjectRunDetail (un solo contrato) y documentar que claves anidan dentro de backendReport vs report.
### [P3] RECOVERY-WIDGET-SCORE-PROXY | conf:media
**RecoveryWidget toma pearson_r/score desde report raiz si no existe bloque recovery, mezclando metricas no relacionadas**
- file: terraquantum-web/componentes/analytics/RecoveryCoverageWidgets.tsx:127-157
- impacto: Si no hay bloque de recuperacion, hace fallback a `report` completo y puede capturar un `status` o `pearson_r` de cualquier otra parte del report (p.ej. status del run) y mostrarlo como 'Recuperacion sintetica'. El score 'EXCELLENT'/'GOOD' de un campo no relacionado pintaria el benchmark de resolucion como valido. El EmptyState honesto solo se muestra si pearson y signPct y score son todos null.
- fix: No hacer fallback a report raiz para metricas de recovery; exigir el bloque dedicado o mostrar EmptyState.
### [P3] RUNCOMPARE-NO-ERROR-UI | conf:alta
**RunCompareSideBySide ignora estados de error de useRunDiagnostics; muestra tabla de '—' como si fuese comparacion valida**
- file: terraquantum-web/componentes/analytics/RunCompareSideBySide.tsx:50-65, 86-104
- impacto: El usuario cree estar comparando dos corridas cuando una (o ambas) fallo al cargar; la tabla de '—' parece 'sin diferencias' o datos faltantes legitimos, no un error de red/persistencia.
- fix: Leer base.error/cmp.error y renderizar un aviso de error explicito por columna en vez de '—' silencioso.
### [P3] DOI-LOWDOIPCT-COMPUTED-FE | conf:media
**DOI 'percent de voxeles <= p50' se recalcula en el frontend sobre cells.doi_raw**
- file: terraquantum-web/componentes/analytics/DoiConfidenceWidget.tsx:50-53, 75-79
- impacto: Estadistico derivado calculado en TS sobre potencialmente miles de celdas en cada render del panel (sin useMemo). Ademas por definicion ~50% de voxeles estaran <= p50 (es la mediana), por lo que el numero es casi siempre ~50% y aporta poca informacion real — metrica cuasi-tautologica presentada como insight.
- fix: Memoizar el calculo o moverlo al backend; reconsiderar si '% <= p50' aporta valor dado que tiende a 50% por construccion.

## Cross-cutting: consistencia de contratos FE<->BE  (P0:0 P1:3 P2:3 P3:3) archivos:29
### [P1] CONTRACT-001 | conf:alta
**exportRunUrl envia 'runId' (camelCase) pero la ruta /api/export-run y el backend exigen 'run_id' (snake_case): la descarga ZIP siempre falla con 400**
- file: terraquantum-web/lib/terraquantum/frontendApi.ts:688-692
- impacto: El boton/enlace 'Exportar corrida' (ZIP industrial) nunca funciona: el proxy recibe runId pero busca run_id, lo encuentra null y devuelve 400. El usuario ve 'project_id y run_id son requeridos' al intentar descargar resultados de una corrida que SI existe. Flujo de exportacion roto de forma silenciosa.
- fix: Cambiar `&runId=` por `&run_id=` en exportRunUrl (linea 690-691) para alinear con la ruta y el backend.
### [P1] CONTRACT-002 | conf:alta
**El proxy /api/gravity-import/preview parsea backendResponse.json() SIN proteccion: cualquier respuesta no-JSON o con NaN del backend produce 'Error interno del proxy' (causa del 'no llega JSON valido')**
- file: terraquantum-web/app/api/gravity-import/preview/route.ts:34
- impacto: Cuando el backend de preview falla de forma no-JSON (error 500 HTML, body vacio, o NaN en observaciones), el frontend muestra 'Error interno del proxy' en vez del detalle real, y el cliente previewGravityCsv solo distingue 'Respuesta no es JSON.' Es exactamente el sintoma 'no llega JSON valido' reportado en la practica.
- fix: Envolver `await backendResponse.json()` en try/catch (leer res.text() primero y JSON.parse con fallback), igual que invert/route.ts y _lib/backend.ts.
### [P1] CONTRACT-003 | conf:media
**El endpoint /preview NO aplica _sanitize_nan: observaciones con g/x_m NaN o Inf serializan 'NaN' (JSON invalido) y rompen el parse del frontend**
- file: terraquantum-backend/api/gravity_import_api.py:597-611
- impacto: Un CSV con una fila de gravedad NaN/Inf (comun en datos reales: celdas vacias, sentinels -9999 mal parseados) hace que el preview emita NaN literal; el proxy preview (CONTRACT-002) o fetchInternalJson devuelven 'no devolvio JSON valido'. El usuario no puede ni previsualizar datos reales con huecos.
- fix: Aplicar `return _sanitize_nan({...})` tambien en el return de preview_gravity_csv, o serializar con un encoder que mapee NaN/Inf a null.
### [P2] CONTRACT-004 | conf:alta
**Contrato roto FE<->BE en /geophysics-invert: el backend es ASINCRONO (devuelve {status:'queued', run_id}) pero el FE lo tipa como BackendInvertResponse sincrono con voxels/best_target/report**
- file: terraquantum-backend/api/geophysics_api.py:48-76
- impacto: Cualquier consumidor que lea result.data.voxels o result.data.report tras runGeophysicsInvert obtiene undefined (modelo vacio interpretado como valido). Hoy esta mitigado porque runGeophysicsInvert/getGeophysicsStatus estan importados pero no se invocan en Exploration3DView (codigo casi-muerto), pero el contrato tipado es enganoso y romperia al cablearse.
- fix: Tipar runGeophysicsInvert como `{status:string; run_id:string; project_id:string}` y consumir voxels/report exclusivamente via getGeophysicsStatus + block-model. Documentar que /geophysics-invert es 202/queued.
### [P2] CONTRACT-005 | conf:media
**GeophysicsInvertInput exige observations (min_length=10) pero /api/geophysics-invert reenvia req.json() crudo: el FE no garantiza ese shape => 422 silencioso**
- file: terraquantum-web/app/api/geophysics-invert/route.ts:16-23
- impacto: Si el caller arma mal el payload (faltan observations o <10), el backend responde 422 con errores Pydantic; el FE solo muestra readBackendMessage(detail). El flujo real de inversion usa /gravity-import/invert (que construye el input en el backend), por eso este endpoint directo es propenso a romperse y esta poco usado.
- fix: Definir un tipo TS GeophysicsInvertPayload espejo del schema y validar minimamente (observations.length>=10) antes de reenviar, o documentar que el unico camino soportado es /gravity-import/invert.
### [P3] CONTRACT-006 | conf:baja
**FavorabilityResult del FE puede tratar campos obligatorios del backend como opcionales; el response_model backend exige gates/scoring_detail/computed_at no-nulos**
- file: terraquantum-backend/schemas/favorability_schema.py:41-52
- impacto: Si el tipo FE difiere (campos opcionales/renombrados), la UI puede renderizar un panel de favorabilidad con valores undefined mostrandose como vacios/0 sin advertir que el contrato cambio. No confirmado por falta de lectura del .ts.
- fix: Diff explicito de favorability_types.ts contra FavorabilityResult del backend; alinear obligatoriedad y nombres de gates/scoring_detail/computed_at.
### [P2] CONTRACT-007 | conf:media
**density default 2.6 y density_max 4.2 hardcodeados como constantes DEMO en el frontend (geophysicsModel.ts) y como defaults del schema backend: enmascaran ausencia de calibracion petrofisica real**
- file: terraquantum-web/lib/terraquantum/geophysicsModel.ts:5-7
- impacto: Constantes de pais/litologia (porfido Cu norte de Chile) viven en el bundle cliente y como defaults del solver. Para cualquier dataset real de otra litologia (magnetita >4.2, BIF) el clip implicito [2.6,4.2] recorta el contraste y el fallback probability=1 pinta vóxeles sin dato como 100% probables: un modelo degenerado se ve 'valido'. Viola la Regla de Oro (fisica solo en backend) al tener densidades de referencia en TS.
- fix: Eliminar las constantes DEMO del FE; que el backend siempre emita density_min/max efectivos y probability por vóxel. El FE no debe inyectar probability=1 por defecto; mostrar 'sin dato' explicito.
### [P3] CONTRACT-008 | conf:media
**Inconsistencia de defaults de URL backend entre _lib/backend.ts y frontendApi.ts: distinta resolucion de env vars puede apuntar a hosts distintos**
- file: terraquantum-web/app/api/_lib/backend.ts:1-2
- impacto: Si solo se define NEXT_PUBLIC_TERRAQUANTUM_BACKEND_URL (caso comun en deploy), los proxies server-side (_lib/backend) caen al default 127.0.0.1:8010 mientras el cliente apunta al host real => deleteRun/footprint/exportBundle funcionan pero invert/block-model/preview pegan a localhost inexistente. Configuracion fragil y dificil de diagnosticar.
- fix: Unificar: _lib/backend.ts debe leer la misma cadena de fallbacks (idealmente solo la var server-side TERRAQUANTUM_BACKEND_URL) y documentar que NEXT_PUBLIC_* es solo para llamadas directas del navegador.
### [P3] CONTRACT-009 | conf:media
**GravityImportMetadata del FE marca como obligatorios campos que el contrato puede omitir, y GravityImportPreviewResponse fija status:'ok'|'error' mientras el backend reenvia result.status arbitrario**
- file: terraquantum-web/lib/terraquantum/frontendApi.ts:788-834
- impacto: Mismatch de tipos en TS: si el backend devuelve un status distinto de ok/error, o omite un metadato opcional, el codigo que confia en obligatoriedad puede acceder a undefined sin guarda. Bajo impacto practico porque casi todos los campos vienen poblados, pero el contrato tipado no refleja la realidad opcional del backend.
- fix: Marcar opcionales los campos que el backend declara Optional y ampliar el union de status a string o agregar fallback.

## Cross-cutting: traza física de punta a punta (densidad/susceptibilidad desde gravimetry.py/magnetometry.py → geophysics_service.py → parquet → block_model_service.py → frontendApi.ts → Scene3D.tsx → terraQuantumGeology.ts)  (P0:1 P1:5 P2:3 P3:2) archivos:8
### [P1] TRACE-01 | conf:alta
**Ejes Norte/Este invertidos en la etiqueta del visualizador (x=Norte en backend vs x=Easting en frontend)**
- file: terraquantum-web/lib/terraQuantumGeology.ts; terraquantum-backend/exploration/magnetometry.py:terraQuantumGeology.ts:304-307; magnetometry.py:31-34
- impacto: El cuerpo recuperado se presenta con su orientación Norte/Este intercambiada respecto a la física real. Una anomalía elongada N-S aparece E-W. El azimut leído del visor 3D o del tooltip (X/Z) está espejado/rotado 90°, invalidando la ubicación direccional para perforación.
- fix: Unificar la convención en un solo lugar: renombrar los comentarios/etiquetas del frontend a x=Norte/z=Este para coincidir con el backend (o transponer explícitamente en serialización). Documentar la convención única en el contrato API.
### [P0] TRACE-02 | conf:alta
**Fallback silencioso joint_structural_score=1.0 en el WebWorker hace que una corrida gravity-only se vea como resultado joint válido (divergencia con el hilo principal)**
- file: terraquantum-web/workers/voxelBufferBuilder.worker.ts; terraquantum-web/lib/terraQuantumGeology.ts:voxelBufferBuilder.worker.ts:376-383; terraQuantumGeology.ts:478-485
- impacto: Para modelos > LOD_WORKER_THRESHOLD (50.000 vóxeles, Scene3D.tsx:547) el render usa el worker; una inversión SOLO gravimétrica (sin datos joint) se muestra como un cuerpo joint completo en cian, fingiendo una inversión conjunta inexistente. El mismo modelo bajo 50k se oculta correctamente. Resultado físicamente engañoso sin aviso, dependiente del tamaño del modelo.
- fix: Replicar la lógica del hilo principal en el worker: si jointRaw es undefined/null → ocultar (scale 0), no asignar 1.0. Idealmente extraer la función de color a un módulo compartido importado por ambos para eliminar la duplicación divergente.
### [P1] TRACE-03 | conf:alta
**Fallbacks density=2.6 / probability=1.0 al serializar celdas enmascaran datos faltantes como roca/objetivo válido**
- file: terraquantum-backend/services/block_model_service.py:679-681; 80; 86
- impacto: Si el parquet llega sin columna density (esquema joint mal mapeado) o nula, cada celda recibe 2.6 t/m³ y probability=1.0. El frontend colorea un bloque uniforme con score de soporte máximo → un modelo vacío/degenerado se ve como resultado físico completo y de alta confianza.
- fix: No inventar densidad ni probabilidad: si la columna física no existe, marcar is_active=False / dejar null y emitir warning explícito. probability ausente debe ser null, no 1.0.
### [P1] TRACE-04 | conf:alta
**El 'relative_target_score' (score de ranking heurístico) se renombra y expone como 'probability' en todo el contrato, induciendo a leerlo como probabilidad estadística**
- file: terraquantum-backend/exploration/gravimetry.py; terraquantum-backend/services/geophysics_service.py:gravimetry.py:1485-1494, 1776; geophysics_service.py:837-838, 956
- impacto: Un número que mide cuán bien explicado queda un vóxel por el ajuste se presenta como 'probabilidad' de objetivo. En un problema sub-determinado el score satura cerca de 1 en celdas con bajo Gᵀ·residual, generando 'probabilidades' altas espurias que el FE traduce en alta favorabilidad. Decisión de targeting basada en una métrica mal etiquetada.
- fix: Eliminar la clave legada 'probability' del contrato o documentarla explícitamente como ranking no-estadístico en el FE; renombrar getVoxelTargetScore para no leer 'probability' como probabilidad. Exponer la incertidumbre estadística real (posterior_std/Hutchinson) por separado y usarla para confianza.
### [P1] TRACE-05 | conf:media
**Cuerpo aplanado a poca profundidad: pocas capas verticales (ny) + depth-weighting β=2 reparten masa sin recuperar profundidad real**
- file: terraquantum-backend/exploration/gravimetry.py:1224-1232; 354-360
- impacto: El cuerpo recuperado tiende a quedar como lámina somera (el reportado '~78 m') en lugar de un volumen a la profundidad real. La interpretación de profundidad de objetivo es poco confiable; con ny bajo el efecto se agrava, y el resultado no comunica esta limitación.
- fix: Aumentar resolución vertical (ny) o malla no-uniforme en Y; calibrar β por física del depósito; reportar DOI/resolución vertical y no presentar la profundidad del pico como dato firme. Validar contra el self-test sintético recuperando profundidad conocida.
### [P1] TRACE-06 | conf:media
**La escala del dominio (157 km) se ve como ~2 km: la grilla colapsa el dominio físico y la cámara hereda el dominio reducido**
- file: terraquantum-backend/services/block_model_service.py; terraquantum-web/componentes/Scene3D.tsx:block_model_service.py:749-751; Scene3D.tsx:1485-1493, 1338-1352
- impacto: Un levantamiento regional de 157 km invertido con grilla/cell_size subdimensionados se renderiza como un cuerpo de ~2 km — escala equivocada. El framing 3D no es el bug raíz; el bug es que el dominio físico no se preserva al construir la grilla; la cámara solo hereda el colapso.
- fix: Garantizar que nx·block_size cubra la extensión real del survey (validar contra span de sensores; build_observation_qaqc_report ya calcula coverage_ratio); advertir/abortar si el dominio de la grilla << extensión de sensores. Mostrar escala métrica real en el visor.
### [P2] TRACE-07 | conf:media
**estimate_grade_from_geophysics: física inventada (ley mineral) derivada de densidad+probability+NIR+Fe+factor regional, usada como anomaly_intensity en el FE**
- file: terraquantum-backend/services/geophysics_service.py; terraquantum-web/lib/terraQuantumGeology.ts:geophysics_service.py:741-773, 800-812; terraQuantumGeology.ts:217
- impacto: Cuando expose_demo_grade=True se fabrica una 'ley' que mezcla densidad gravimétrica con índices satelitales (NIR/Fe) y un factor regional arbitrario — no es física ni assay. El FE la usa para anomaly_intensity y filtros de visibilidad, dirigiendo la visualización de anomalías con un número inventado.
- fix: Mantener grade fuera del pipeline de anomalías (ya excluido en build_anomaly_dataframe, correcto) y que el FE NO use 'grade' como anomaly_intensity salvo en una capa demo claramente rotulada.
### [P2] TRACE-08 | conf:alta
**Defaults del FE inventan física de densidad (2.6 / 2.75) cuando faltan campos, coloreando vóxeles sin dato**
- file: terraquantum-web/lib/terraQuantumGeology.ts; terraquantum-web/componentes/Scene3D.tsx:terraQuantumGeology.ts:221-228, 240-241; Scene3D.tsx:131-139
- impacto: Si una celda llega sin density el FE asume 2.6 t/m³ y calcula un density_anomaly_score local — física calculada en TS (prohibido por reglas del proyecto) que produce color/score para una celda sin dato real; un modelo con densidades nulas se ve como roca país coherente en lugar de vacío.
- fix: No fabricar densidad ni recalcular anomaly score en TS; si density es null/ausente, ocultar la celda. El density_anomaly_score debe venir del backend (única fuente de física).
### [P2] TRACE-09 | conf:media
**build_best_target colapsa probability/density faltantes a 0.0/2.6 dentro del max(), pudiendo serializar un 'mejor objetivo' degenerado**
- file: terraquantum-backend/services/geophysics_service.py:952-959, 975-990
- impacto: En un modelo sin señal, el endpoint igualmente devuelve un best_target (el primer vóxel), presentando un objetivo de perforación donde no hay nada. confidence_level (966-973) puede no degradarse a UNKNOWN.
- fix: Si el score máximo es 0 o los campos físicos son None, devolver best_target=None; validar que density/probability del best sean finitos antes de exponerlo.
### [P3] TRACE-10 | conf:media
**ensure_visual_columns rellena grade=0.0 / domain=0 / tonnage=0.0 que se propagan como ceros físicos**
- file: terraquantum-backend/services/block_model_service.py:100-108; 612-619
- impacto: Bajo riesgo: domain=0 y tonnage=0 fabricados pueden propagarse a UI/exports como ceros físicos en vez de 'sin dato', enmascarando ausencia de columnas reales.
- fix: Usar null en lugar de 0.0 para columnas físicas ausentes y exponer un warning de 'columna fabricada'.
### [P3] TRACE-11 | conf:media
**infer_cell_size devuelve 10.0 m por defecto silencioso, distorsionando domainL/H/W y la escala del visor**
- file: terraquantum-backend/services/block_model_service.py:112-125; 605-607; 749-751
- impacto: Si el parquet carece de coords reales y el block_size real no es 10 m, el dominio reportado y la escala del visor quedan mal (un dominio real de 157 km se reduciría a nx·10 m). Fallback plausible que oculta el block_size real.
- fix: Persistir block_size real en el parquet/manifest y usarlo; si se debe inferir y falla, emitir warning en la respuesta en vez de asumir 10 m.