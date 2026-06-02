# Informe de Madurez Tecnologica y Analisis Competitivo - TerraQuantum V2

Fecha de auditoria: 2026-05-31  
Rol asumido: CTO, Arquitecto Principal B2B y Geofisico Jefe  
Alcance: lectura arquitectonica del repositorio actual, backend Python/FastAPI, algoritmos NumPy/SciPy, frontend React/Three.js, documentacion local y contraste competitivo publico.  
Restriccion operativa: no se corrigieron bugs, no se escribio codigo de producto y no se ejecutaron pruebas. Este informe es una auditoria de lectura.

## Veredicto Ejecutivo Brutal

TerraQuantum V2 no es hoy un producto industrial Tier-1 vendible manana a una minera transnacional sin un piloto controlado, contratos de riesgo, validacion externa y refactor de infraestructura. Es un prototipo avanzado, tecnicamente ambicioso, con piezas matematicas serias y varias decisiones correctas, pero todavia con brechas duras de fisica, trazabilidad, escalabilidad, compliance, transporte de datos y operaciones.

La afirmacion mas honesta es esta: el nucleo matematico ya dejo de ser una maqueta visual superficial; hay inversion de gravedad con kernels fisicos, inversion magnetometrica inducida, regularizacion tipo Li & Oldenburg, LSQR sparse, incertidumbre aproximada por Hutchinson, DOI, checkerboard y una inversion conjunta alternada con restriccion estructural tipo cross-gradient. Eso es defendible como I+D geofisica. Pero el producto completo no es defendible como herramienta operacional de decision minera. La cadena se rompe entre solver, persistencia, API, frontend, georreferenciacion fisica, topografia, jobs, memoria, seguridad y validacion independiente.

Si manana se sienta un geofisico senior de Codelco o BHP, yo defenderia la direccion cientifica, no la madurez del producto. Defenderia que usamos familias de metodos reconocidas: Tikhonov, Li & Oldenburg, LSQR, cross-gradients, clustering determinista y guardrails de compliance. No defenderia todavia los resultados como base de perforacion, recursos, reservas o CAPEX. El README raiz dice explicitamente que TerraQuantum es una plataforma experimental/conceptual y no una herramienta de decision minera, recursos, reservas ni factibilidad. Ese disclaimer no es maquillaje legal: describe correctamente el estado actual.

Puntuacion de madurez estimada:

- Motor geofisico conceptual: 7/10.
- Implementacion numerica industrial: 4.5/10.
- Trazabilidad y auditabilidad de corridas: 5.5/10.
- Escalabilidad compute/browser: 3/10.
- Georreferenciacion y terreno real: 4/10.
- Compliance de lenguaje minero: 6/10 en reportes estructurados, 3/10 en chat general.
- Preparacion B2B enterprise: 2.5/10.
- Diferenciacion estrategica: 8/10.

Conclusion: TerraQuantum V2 esta en TRL 4-5. Puede usarse para demos tecnicas serias, pilotos internos, benchmarks sinteticos y conversaciones de innovacion. No debe venderse aun como software industrial de interpretacion geofisica certificable.

## Fase 1 - Inventario Arquitectonico

### 1.1 Estructura general del repositorio

El repositorio contiene dos productos principales:

- `terraquantum-backend`: API FastAPI, servicios de inversion, almacenamiento local de corridas, importacion CSV, exportes, agente Gemini, terreno, favorabilidad, espectral y modulos economicos gated.
- `terraquantum-web`: frontend Next/React, Three.js/@react-three/fiber, Zustand, paneles de CSV, historial, escena 3D, chat IA, controles de modelo.

Hay carpetas de soporte como `docs`, `benchmarks`, `tmp`, `_audit_upload_2`, `.github` y documentacion estrategica previa. El stack no es una maqueta estatica: hay servicios, tests, benchmarks, planes de industrializacion, exportes Parquet/VTR/GLB y contratos de corridas.

### 1.2 Stack tecnologico backend

Backend:

- FastAPI con routers modulares.
- Uvicorn como servidor.
- Pydantic para schemas.
- NumPy/SciPy para algebra numerica, CSR, KDTree, LSQR, CG.
- Polars para Parquet y analisis tabular.
- PyProj para transformaciones reales de coordenadas.
- Trimesh, NetworkX, Shapely y pyevtk para geometria/exportes.
- SlowAPI para rate limiting.
- `google-generativeai` para Gemini.
- PyTest y tests geofisicos/espaciales.

Arquitectonicamente el backend se organiza alrededor de:

- `main.py`: compone FastAPI, CORS, static files, rate limiter y routers.
- `core/config.py`: rutas runtime, limites de CSV, flags de CORS y nombres estandar de artefactos.
- `core/block_model_store.py`: filesystem project/run store, metadata, status atomico, source CSV, reportes, export ZIP.
- `api/*`: routers para geophysics, gravity import, block model, report, project, terrain, favorability, spectral, export, chat y modulos economicos opcionales.
- `services/*`: logica de importacion, inversion, coordenadas, terreno, reporting, Gemini, block model y joint inversion.
- `exploration/*`: kernels, inversion y clustering fisico.

El backend tiene buena separacion por dominio, pero todavia mezcla responsabilidades en servicios grandes. `geophysics_service.py` es el orquestador critico y acumula demasiado: validacion, mallado, inversion, diagnosticos, incertidumbre, DOI, QA, focalizacion, persistencia y reporte.

### 1.3 Stack tecnologico frontend

Frontend:

- Next 16 / React 19.
- Three.js 0.183, @react-three/fiber y drei.
- Zustand para estado global.
- Apache Arrow instalado y wrappers existentes.
- Recharts, framer-motion, lucide-react.

Componentes clave:

- `app/page.tsx`: experiencia principal con `WelcomeScreen`, navegacion, vista 3D, datos, historial y chat.
- `store/useAppStore.ts`: estado global de corridas, block model, controles 3D, georreferencia, modo de fisica, seleccion, polling y UI.
- `components/exploration/Exploration3DView.tsx`: carga modelos y conecta UI con escena 3D.
- `components/exploration/Scene3D.tsx`: render WebGL con instancing.
- `lib/terraquantum/frontendApi.ts`: cliente hacia rutas Next/API y backend.
- `app/api/block-model/route.ts`: proxy JSON/Arrow hacia backend.

La UI esta bastante mas madura que una demo de tres botones. Hay historial de corridas, active run, CSV preview, readiness gates, paneles de interpretacion y controles multi-fisica. La brecha no esta en que “no se ve profesional”; la brecha esta en que parte de la data multi-fisica no llega al navegador por el contrato actual.

### 1.4 Flujo de datos completo

Flujo conceptual actual:

1. El usuario sube un CSV de gravedad/anomalias en el frontend.
2. El panel de CSV llama al backend de importacion.
3. `gravity_import_api.py` aplica limite de tamano, lee columnas, detecta alias, valida unidades, coordenadas y gravedad.
4. `gravity_import_service.py` normaliza unidades: mGal/uGal a SI, clasifica tipo de gravedad, revisa duplicados, zeros, rangos y variabilidad.
5. Servicios de coordenadas y readiness estiman si hay lat/lon, UTM, local grid, huella espacial, confianza georreferenciada y escala regional.
6. Si pasa preflight, se construye `GeophysicsInvertInput`: profundidad, nx/ny/nz, block size, cutoff, lambda, alpha, observaciones, lat/lon y opcionalmente magnetometria.
7. `geophysics_service.py` valida limites duros: voxeles maximos, observaciones minimas, profundidad, cutoff, coordenadas finitas.
8. Se construye una malla tensorial con padding geometrico.
9. Si solo hay gravedad, entra `GravimetryInversion`; si hay magnetometria y gravedad real, entra `run_joint_inversion`; si hay magnetometria sin gravedad real, entra inversion magnetica.
10. El solver arma kernels sparse CSR, regularizacion, pesos de dato, pesos de profundidad, precondicionamiento por escalamiento de columnas y resuelve por LSQR.
11. Se recortan celdas de padding, se calculan diagnosticos, incertidumbre, DOI, checkerboard, targeting/favorabilidad y focalizacion.
12. Se persiste Parquet de block model, Parquet de anomalias, JSON de reporte, snapshots y opcional VTR.
13. El frontend consulta `/block-model` en modo exploration/full/anomaly.
14. El backend transforma Parquet a JSON de celdas limitado por sampling.
15. `Scene3D` crea un `InstancedMesh`, asigna matriz/color por voxel y permite modo densidad/susceptibilidad/joint, seleccion y tooltip.
16. El panel React muestra narrativa geologica, metricas, interpretacion, alertas y chat.

Ese flujo existe. Pero no esta cerrado industrialmente. La ruta Arrow existe pero esta muerta en la UI principal. El modelo conjunto puede persistirse en `block_model_joint.parquet`, pero la API estandar de block model espera `block_model.parquet` y columnas estandar como `ix/iy/iz` o `x/y/z`; el joint parquet usa `x_c/y_c/z_c` y `x_m/y_m/z_m`. Ademas, el servicio JSON/Arrow descarta campos como `susceptibility_si` y `joint_structural_score`. Resultado: el frontend tiene controles multi-fisica, pero no necesariamente recibe la fisica que dice visualizar.

### 1.5 Motor matematico: gravedad

El motor de gravedad tiene una base real:

- Usa malla de prismas rectangulares.
- Usa kernel de Nagy/prisma en campo cercano y aproximacion de masa puntual en campo lejano.
- Usa `cKDTree` para limitar interacciones dentro de cutoff.
- Construye matriz CSR para sensibilidad.
- Aplica pesos de dato adaptativos.
- Regulariza con Laplaciano sparse y smallness.
- Incorpora anclajes de sondajes/boreholes.
- Usa profundidad tipo Li & Oldenburg para compensar decaimiento de sensibilidad.
- Resuelve con LSQR.
- Estima incertidumbre posterior via diagonal aproximada de inversa por Hutchinson + CG.

Esto ya es sustancial. No es un shader pintando cubos. Hay geofisica computacional en serio.

Limitaciones criticas:

- Las cotas fisicas de densidad se aplican por clipping post-solve, no como inversion acotada real.
- La topografia no entra como active-cell real en el flujo de inversion principal; las capacidades existen, pero el servicio opera esencialmente con topografia plana.
- La incertidumbre es aproximada y costosa; no sustituye posterior robusto ni analisis de resolucion formal.
- La matriz CSR explicita no escala bien a millones de voxeles y muchas estaciones.
- Hay una ruta que, ante misfit extremadamente bajo, inyecta ruido aleatorio en observaciones y rerun. En produccion, alterar observaciones reales para evitar un resultado “demasiado perfecto” es inaceptable salvo que este estrictamente confinado a modo sintetico/test y registrado con semilla/provenance.

### 1.6 Motor matematico: magnetometria

La magnetometria implementa un modelo TMI inducido:

- Campo unitario por inclinacion/declinacion.
- Susceptibilidad SI.
- Kernel dipolar inducido.
- CSR, KDTree, ThreadPool.
- LSQR con regularizacion, profundidad y anclajes.
- Clipping de susceptibilidad a bounds.

La decision es correcta para una primera fase. Pero no es industrial en zonas mineras complejas si se presenta como solucion general:

- No modela magnetizacion remanente.
- No estima vector magnetico.
- No resuelve MVI.
- No corrige IGRF, diurnas, heading, leveling, microleveling o procesamiento magnetico completo.
- El campo inducido unicamente puede fallar brutalmente en geologias con remanencia, volcanicas, intrusivos magnetizados o magnetita con historia termica compleja.

VOXI y herramientas comerciales destacan MVI justamente porque la hipotesis de magnetizacion paralela al campo terrestre falla con frecuencia.

### 1.7 Inversion conjunta alternada

La inversion conjunta es una de las mejores ideas de TerraQuantum V2:

- Alterna gravedad y magnetometria.
- Usa regularizacion cruzada inspirada en Gallardo & Meju.
- Construye bloques de cross-gradient a partir de gradientes normalizados.
- Incrementa `lambda_cross` por continuation exponencial.
- Calcula energia estructural normalizada, no solo metrica global dependiente de N.
- Persiste historia de convergencia y centroides.
- Usa clustering determinista sobre anomalias conjuntas.

La formulacion conceptual es defendible: si densidad y susceptibilidad responden a cuerpos geologicos relacionados, alinear estructuras puede reducir no-unicidad. Pero hay que ser precisos: lo que hay no es una inversion conjunta plenamente acoplada estilo Gauss-Newton monolitica con Jacobiano completo de ambos problemas y restriccion cross-gradient resuelta simultaneamente. Es una alternancia secuencial con bloques de regularizacion cruzada. Eso puede funcionar y es defendible como aproximacion, pero no debe venderse como equivalente a un framework UBC/SimPEG completo sin benchmarks.

Tambien hay una brecha de integracion muy grave: el resultado conjunto no parece circular limpiamente por el contrato estandar de block model. Se persiste un parquet con columnas especificas, pero el servicio de visualizacion espera otro esquema y ademas elimina campos de susceptibilidad/joint score. Para CTO, este es un fallo de producto: el solver puede producir fisica, pero la cadena de valor no la conserva hasta el usuario.

### 1.8 Clustering fisico con `I_joint`

El clustering no es DBSCAN de scikit-learn puro; es una version determinista tipo DBSCAN/connected components:

- Calcula intensidad relativa de densidad `I_rho`.
- Calcula intensidad relativa de susceptibilidad `I_chi`.
- Combina como `I_joint = sqrt(I_rho^2 + I_chi^2)`.
- Filtra voxeles por threshold.
- Construye vecindad por KDTree con radio dependiente del tamano de celda.
- Usa componentes conectados sparse.
- Reporta volumen, centroide, densidad, susceptibilidad, maximos y correlacion.

Esto es una buena eleccion para compliance: el LLM no inventa blancos desde pixeles; recibe cuerpos definidos por reglas reproducibles. Es mas sano que pedirle a Gemini “mira el modelo y dime donde perforar”.

Debilidad: si el transporte de `susceptibility_si` y `joint_structural_score` falla hacia el frontend, el usuario ve una interpretacion parcial. El clustering puede estar correcto en backend y aun asi la experiencia SaaS mentir visualmente por omision.

### 1.9 Render WebGL

La escena 3D usa `InstancedMesh` con cubos instanciados:

- Una geometria base.
- Matrices por instancia.
- Color por instancia.
- Filtros por densidad, incertidumbre, profundidad, percentiles y modo.
- Tooltip y picking por `instanceId`.
- Modo densidad, susceptibilidad y joint.

Para 5k a 150k voxeles muestreados, es razonable. Para 250k, ya depende de GPU/browser. Para 5 millones, no es arquitectura valida: `InstancedMesh` con matrices completas y objetos JS por voxel explota memoria, tiempo de subida a GPU y re-render updates O(n). El frontend necesita streaming, LOD, octree, tiles, workers, buffers binarios y quizas WebGPU/volume rendering. El estado actual sirve para visualizacion exploratoria limitada, no para modelos industriales grandes.

### 1.10 Agente Analitico Gemini

Hay dos realidades:

1. `gemini_agent.py` esta bastante bien pensado:
   - Prompt de rol geofisico.
   - Temperatura baja.
   - JSON estructurado.
   - Validacion Pydantic.
   - Palabras prohibidas: reserve, resource, grade, NPV, IRR, tonnage, economic value.
   - Fallback si no hay API key.
   - Disclaimer de que no estima reservas.

2. `chat_api.py` es una brecha:
   - El prompt menciona estimacion de recursos minerales.
   - Carga reportes completos.
   - No tiene el mismo filtro de palabras prohibidas.
   - No tiene validacion estructurada equivalente.

Compliance no puede depender de que “el reporte estructurado esta blindado” si el chat general puede decir lo que el reporte tiene prohibido. En mineria Tier-1, el lenguaje importa: una frase indebida puede parecer una estimacion de recurso no calificada.

Ademas, el codigo usa `gemini-1.5-pro`. La pagina oficial de Google consultada el 2026-05-31 muestra que la familia 2.5/3.x es el carril vigente y que modelos anteriores tienen calendarios de shutdown/reemplazo. Esto convierte el modelo LLM en deuda operacional temporal.

## Fase 2 - Test de Grado Industrial

### 2.1 Que significa "Grado Industrial" en mineria

En software minero, "grado industrial" no significa que la UI sea bonita. Significa:

- Fisica defendible bajo revision de pares.
- Datos crudos preservados, nunca alterados sin provenance.
- Unidades, CRS, datum, elevacion y procesamiento trazables.
- Reproducibilidad bit a bit o al menos estadisticamente controlada.
- Sensibilidad a ruido y outliers caracterizada.
- Tests sinteticos no triviales y benchmarks con verdad conocida.
- Evitar inverse crimes: no validar con el mismo mallado/forward que genera el dato.
- Escalabilidad demostrada con tamanos de cliente.
- Seguridad, RBAC, auditoria, logs, tenancy y backups.
- Exportes interoperables.
- Limitaciones explicitas: no recursos/reservas si no hay QP y workflow JORC/NI 43-101.
- Observabilidad: cada corrida debe explicar datos, parametros, warnings, version de codigo, solver, tolerancias, semilla, ambiente y artefactos.

### 2.2 Precision fisica

TerraQuantum tiene buena direccion fisica: prismas, kernels de gravedad, dipolos magneticos, regularizacion por profundidad y restricciones estructurales. Pero precision industrial exige mas:

- Topografia real como active cells.
- Terreno y Bouguer/Faye/free-air correctos si el dato lo requiere.
- Correcciones magneticas completas.
- Remanencia/MVI o advertencia dura.
- Data covariance real, no sigma heuristica solamente.
- Survey line handling, tie-lines, leveling, grids, datum vertical.
- Validacion contra casos UBC/SimPEG/VOXI o datasets publicos.

Hoy la precision fisica es defendible para prototipos y sintéticos; no para produccion minera sin supervisión experta.

### 2.3 Estabilidad matematica

Fortalezas:

- CSR sparse.
- LSQR para problemas grandes/ill-posed.
- Pesos de dato y escalamiento de columnas.
- Laplaciano sparse.
- Diagnosticos de chi2, condicion, dead voxels, saturation.
- Continuation en cross-gradient.
- Estimacion de incertidumbre aproximada.

Debilidades:

- Bounds por clipping no son bounds de optimizacion.
- No hay solver acotado tipo projected GN, TRF, L-BFGS-B o primal-dual.
- No hay robust norms Lp/Huber para outliers.
- No hay matrix-free para problemas grandes.
- No hay estrategia out-of-core.
- No hay precondicionadores industriales mas alla de Jacobi/escalamiento.
- Posterior/DOI/checkerboard multiplican costo y pueden no ser viables.

LSQR es correcto; la arquitectura alrededor de LSQR todavia no es industrial.

### 2.4 Trazabilidad

Mejoras existentes:

- Run store por project/run.
- Status atomico.
- Persistencia de source CSV.
- Metadata de georreferencia.
- Reportes JSON.
- Export ZIP.
- Disclaimers economicos.

Brechas:

- No hay manifiesto inmutable completo con hash de input, hash de codigo, version de dependencias, parametros exactos, seed, warnings, ramas de decision y artefactos.
- No hay auditoria multiusuario.
- No hay lineage entre CSV crudo, dato corregido, dato invertido y modelo final.
- No hay firma de reporte.
- El chat puede escapar del marco de compliance.

### 2.5 Escalabilidad

El codigo impone limite de 200.000 voxeles para inversion. Eso es honesto. Pero significa que 5 millones de voxeles no es un caso soportado. Con padding geometrico, un grid nominal grande crece aun mas. Matrices CSR explicitas de gravedad/magnetometria, regularizacion, DOI, incertidumbre y checkerboard pueden entrar en decenas de GB si el numero de estaciones y vecinos crece.

En navegador, 5 millones de voxeles como objetos JS + matrices de instancia + colores + buffers + filtros reactivos no es viable. Un solo `instanceMatrix` de 5M con 16 floats de 4 bytes son ~320 MB solo en matrices GPU, sin colores, atributos, objetos, JSON, overhead JS ni duplicaciones. JSON de millones de celdas seria absurdamente pesado.

Industrial no puede depender de "limit=5000" para verse fluido. Necesita arquitectura de visualizacion progresiva.

### 2.6 Es defendible ante Codelco/BHP?

La respuesta honesta:

- La base Li & Oldenburg para gravedad/magnetismo: si, defendible como familia metodologica.
- La inversion conjunta por cross-gradient: si, defendible como principio, con citas y limites.
- La implementacion actual: defendible como prototipo I+D, no como herramienta validada.
- Los resultados numericos: no defendibles sin benchmarks, topografia real, correcciones de campo, incertidumbre calibrada y trazabilidad.
- El uso de LLM: defendible solo si se presenta como asistente narrativo sobre resultados deterministas, nunca como motor de estimacion ni recomendador autonomo de perforacion.

Mi frase frente a un geofisico senior seria: "El metodo esta inspirado en literatura seria, pero esta implementacion aun requiere validacion independiente y hardening antes de que yo firme una decision operacional con esto."

## Fase 3 - Analisis Competitivo

### 3.1 Seequent Oasis montaj y VOXI

Seequent declara Oasis montaj como software estandar de la industria para procesar, filtrar, modelar e interpretar datos geofisicos, con manejo de grandes volumenes y transformaciones de coordenadas. VOXI es aun mas relevante: documentacion publica lo describe como servicio cloud de forward modelling e inversion para campos potenciales magneticos y gravitacionales. VOXI invierte gravedad, magnetismo, gradientes, FTG/AGG, genera distribuciones 3D de densidad/susceptibilidad/magnetizacion y usa regularizacion Tikhonov. Ademas incluye cut-cell topography, IRIF focusing y MVI.

Conclusion competitiva: TerraQuantum no puede afirmar "nadie tiene inversion 3D cloud". VOXI ya existe y es serio. La diferencia potencial de TerraQuantum es otra: SaaS web-native, API-first, interpretacion automatizada con LLM guardado, clustering determinista, UX de exploracion directa y compliance anti-reservas.

### 3.2 SimPEG / UBC-GIF

SimPEG es open source, Python, modular, soporta gravedad, magnetica, DC/IP, EM, OcTree, regularizacion, data misfit, optimizacion y joint inversions. Tiene tutorial explicito de inversion conjunta cross-gradient de gravedad y magnetica. UBC-GIF es la fuente canonica historica de muchas formulaciones Li & Oldenburg y codigos GRAV3D/MAG3D.

Conclusion competitiva: TerraQuantum no supera a SimPEG en rigor cientifico ni ecosistema numerico. Su oportunidad es producto: convertir workflows complejos en una plataforma operable por equipos de exploracion, con gobierno, visualizacion y reporte. Si el core cientifico no alcanza validacion tipo SimPEG/UBC, la capa SaaS no salva el producto.

### 3.3 Datamine, Hexagon, Maptek y plataformas mineras

Datamine Studio RM se posiciona como estandar industrial para modelamiento geologico, geoestadistica, estimacion de recursos y evaluacion con compliance JORC/NI 43-101/S-K 1300. Hexagon MinePlan y otros compiten en resource geology, block models, mine planning, reservas y scheduling.

Estas plataformas son muy fuertes en downstream minero. TerraQuantum no debe competir ahi todavia. Debe ubicarse upstream: exploracion geofisica cuantitativa y priorizacion de targets, explicitamente antes de recursos/reservas.

### 3.4 SLB Delfi y plataformas subsurface cloud

SLB Delfi es una plataforma cloud, abierta, escalable y segura para E&P, con 24/7 support, Petrel, Techlog, data science y workflows de energia. No es un competidor directo de mineria de cobre/oro, pero muestra que el mercado enterprise espera cloud, seguridad, AI, integracion y soporte operacional. TerraQuantum esta lejos de esa madurez enterprise.

### 3.5 Fase 10: LLM + clustering determinista + compliance

Aqui TerraQuantum si tiene una idea diferenciada:

- No deja que el LLM invente cuerpos.
- Usa clustering fisico reproducible.
- Entrega un reporte estructurado.
- Prohibe lenguaje de reservas/recursos/economia.
- Mantiene el LLM en rol interpretativo.

Existe AI en geociencia comercial, y existe cloud geoscience. Pero una combinacion vertical de inversion conjunta web + clustering fisico + reporte geofisico LLM con guardrails anti-JORC/NI 43-101 no aparece como commodity comercial ampliamente establecido. Esto es innovacion real en la interseccion IA/geofisica, siempre que se cierre el bypass del chat y se valide que el LLM no degrade compliance.

## Fase 4 - Brechas hacia Grado Industrial Tier-1

### 4.1 Brechas criticas para vender manana

No vendible manana por:

- Sin autenticacion/RBAC/multitenancy enterprise.
- Sin storage cloud robusto.
- Sin cola de jobs real.
- Sin cancelacion/retry/resume.
- Sin observabilidad.
- Sin validacion independiente.
- Sin benchmarks de campo.
- Sin contrato de datos multi-fisica cerrado.
- Sin topografia fisica real en inversion.
- Sin MVI/remanencia.
- Sin solver out-of-core.
- Sin auditoria de compliance completa.
- Con dependencia faltante probable: el importer usa pandas, pero requirements no lo declara.

La dependencia faltante es simbolica: si un contenedor limpio falla importando CSV, el producto no puede siquiera pasar un PoC formal.

### 4.2 5 millones de voxeles

Con 5M voxeles, hoy:

- El backend lo rechazaria por limite de voxeles.
- Si se levanta el limite, el solver probablemente colapsa por memoria/tiempo.
- La matriz CSR explicita no es el camino correcto.
- DOI/incertidumbre/checkerboard multiplicarian el problema.
- El navegador no puede recibir JSON de 5M celdas.
- `InstancedMesh` por voxel tampoco es suficiente como unica estrategia.

Arquitectura requerida:

- Forward operators matrix-free.
- Multiplicaciones `G @ m` y `G.T @ r` sin construir toda G.
- OcTree/adaptive mesh.
- Out-of-core arrays con Zarr/TileDB/Parquet partitioned.
- Workers HPC con Dask/Ray/Kubernetes.
- Precomputacion de tiles multiresolucion.
- Streaming Arrow real, no conversion a objetos JS.
- WebWorkers y binary buffers.
- LOD/octree en cliente.
- Seleccion y queries server-side.
- Render con instancing por tiles, point clouds, volume textures o WebGPU.

### 4.3 Georreferenciacion

TerraQuantum ya avanzo en:

- Deteccion de lat/lon y UTM.
- Estimacion EPSG/UTM.
- PyProj para footprints.
- Readiness espacial.
- Preflight regional.
- DEM/terreno visual/enrichment.

Pero falta:

- CRS obligatorio y explicito por dataset.
- Datum horizontal y vertical.
- Transformacion auditada de cada estacion.
- Elevacion real por estacion.
- Topografia como active cells en inversion.
- Terrain correction fisica.
- Soporte de sondajes desviados.
- Persistencia CRS por voxel y por export.
- Exportes interoperables a Leapfrog/Oasis/Datamine con metadata espacial completa.

Hoy la georreferenciacion es un excelente preflight, pero no una cadena fisica completa.

### 4.4 Deuda tecnica

Deuda dura:

- `geophysics_service.py` demasiado grande.
- Contrato block model inconsistente entre gravity, joint, frontend y Arrow.
- Arrow existe pero no se usa realmente en UI.
- Chat IA no comparte guardrails del agente estructurado.
- Economicos gated pero presentes; riesgo reputacional si se activan mal.
- Campos `probability`, `tonnage` y lenguaje historico siguen contaminando el modelo mental del producto.
- CSV import depende de pandas no declarado.
- Random noise injection en observaciones.
- No hay separacion clara entre demo/synthetic/prod modes.
- No hay versionado formal de schemas de artefactos.

## Fase 5 - Consejos Estrategicos y Roadmap V3.0

### 5.1 Principio rector V3

V3 no debe ser "mas visual". V3 debe ser: fisica trazable + contratos de datos inmutables + computo escalable + compliance cerrado + benchmarks reproducibles. La UI debe mostrar menos si la fisica no existe. Honestidad antes que espectacularidad.

### 5.2 Roadmap tecnico

Hito 0 - Congelamiento semantico:

- Eliminar/renombrar campos que sugieren recursos, reservas, tonnage, grade o economic value.
- Separar namespaces `exploration_signal`, `geophysical_anomaly`, `ranking_score`.
- Definir politica de compliance unica para report, chat, export y UI.

Hito 1 - Contrato de artefactos:

- Crear schema versionado para `block_model`.
- Unificar columnas: `cell_id`, `ix/iy/iz`, `x/y/z`, `crs`, `density_contrast`, `susceptibility`, `joint_score`, `uncertainty`, `doi`, `source_run`.
- Hacer que joint, gravity-only y mag-only usen el mismo contrato.
- Validar artefactos antes de persistir.

Hito 2 - Provenance industrial:

- `run_manifest.json` inmutable.
- Hash de CSV raw.
- Hash de parametros.
- Version de codigo.
- Version de dependencias.
- Semilla RNG.
- Solver, tolerancias, iteraciones, warnings.
- CRS/datum/elevacion.
- Artefactos generados y checksums.

Hito 3 - Fisica de campo:

- Correcciones de gravedad: drift, tide, free-air, Bouguer, terrain segun input.
- Correcciones magneticas: IGRF, diurnal, leveling, microleveling, RTP/RTE si aplica.
- Topografia activa en inversion.
- DEM con fuente, resolucion y datum.
- Sondajes desviados y logs por intervalo real 3D.

Hito 4 - Solver V3:

- Matrix-free forward operators.
- Bound-constrained inversion real.
- Robust norms para outliers.
- LSMR/LSQR interchangeable.
- Precondicionadores mejores.
- OcTree/adaptive mesh.
- Cross-gradient fully coupled opcional.
- MVI o al menos ruta remanence-aware.

Hito 5 - Escalabilidad cloud:

- Queue workers: Celery/RQ/Arq o Temporal.
- Kubernetes jobs.
- Object storage S3/Azure Blob.
- Parquet/Zarr partitioned.
- Job cancellation/resume.
- Resource quotas.
- Logs estructurados y metrics.
- Prometheus/Grafana/OpenTelemetry.

Hito 6 - Frontend industrial:

- Usar Arrow real en UI.
- No convertir millones de filas a objetos JS.
- WebWorker parsing.
- Tile streaming.
- LOD/octree.
- Picking server-side o por tile.
- Visual validation con datasets grandes.
- Modo comparativo gravity/mag/joint sincronizado.

Hito 7 - Validacion cientifica:

- Suite analitica: esfera, prisma, dique, contacto.
- Benchmarks Li & Oldenburg.
- Benchmarks SimPEG.
- Inverse-crime prevention: malla forward distinta a malla inversion, ruido realista, outliers, topografia.
- Datasets publicos.
- Reporte de precision y failure modes.

Hito 8 - Enterprise:

- Auth/OIDC/SAML.
- RBAC.
- Tenant isolation.
- Audit logs.
- Encryption at rest/in transit.
- Backup/restore.
- Data retention.
- Admin console.
- Security review.

### 5.3 Cinco consejos tecnicos expertos

1. Adoptar arquitectura hexagonal: dominio geofisico puro, adaptadores API, adaptadores storage, adaptadores UI. El solver no debe saber que existe FastAPI ni React.

2. Tratar los tests de inversion como ensayos cientificos, no como unit tests normales. Cada benchmark debe declarar geometria verdadera, ruido, mallado forward, mallado inverse, tolerancia y criterio de fallo.

3. Prohibir inverse crimes por politica. Si generas sinteticos con el mismo forward, misma malla y mismo ruido ideal con que inviertes, solo demuestras consistencia interna, no recuperabilidad geologica.

4. Construir V3 alrededor de operadores matrix-free y datos chunked. Si primero armas CSR gigante y luego buscas optimizar, llegaras tarde.

5. Compliance como compilador, no como prompt. Cada salida humana debe pasar por validador de politica, no solo confiar en que el prompt del LLM obedece.

## Fase 6 - Revision Bibliografica e Investigacion Obligatoria

### 6.1 Teoria de inversion geofisica

1. Tikhonov, A. N. y Arsenin, V. Y. - Solutions of Ill-Posed Problems. Base de regularizacion.
2. Parker, R. L. - Geophysical Inverse Theory. Lectura esencial sobre no-unicidad.
3. Tarantola, A. - Inverse Problem Theory. Marco probabilistico.
4. Menke, W. - Geophysical Data Analysis: Discrete Inverse Theory. Fundamentos practicos.
5. Li, Y. y Oldenburg, D. W. (1996) - 3-D inversion of magnetic data. Positivity, depth weighting, induced magnetization.
6. Li, Y. y Oldenburg, D. W. (1998) - 3-D inversion of gravity data. Depth weighting y no-unicidad de gravedad.
7. Zhdanov, M. S. - Geophysical Inverse Theory and Regularization Problems. Tikhonov, focusing e interpretacion.
8. Nagy, D. - The gravitational attraction of a right rectangular prism. Kernel clasico de prisma.
9. Portniaguine, O. y Zhdanov, M. S. - Focusing geophysical inversion images. Focalizacion compacta.

### 6.2 Inversion conjunta

10. Gallardo, L. A. y Meju, M. A. (2003/2004) - Cross-gradients joint inversion. Piedra angular para structural similarity.
11. Haber, E. y Oldenburg, D. W. - Joint inversion and coupling methods. Marco numerico.
12. Moorkamp, M., Heincke, B., Jegen, M., Roberts, A. y Hobbs, R. - Joint inversion in geophysics: theory and applications.
13. Astic, T. y Oldenburg, D. W. - Petrophysically and geologically guided inversion en SimPEG.
14. Gao/Zhang y trabajos recientes de gravity-magnetic joint inversion con Lp/cross-gradient. Relevante para robust norms.
15. Ellis, de Wet y MacLeod - Inversion of Magnetic Data from Remanent and Induced Sources. Necesario para MVI.

### 6.3 Metodos numericos

16. Paige, C. C. y Saunders, M. A. (1982) - LSQR: sparse linear equations and least squares.
17. Fong, D. C.-L. y Saunders, M. A. - LSMR. Alternativa con mejores propiedades de terminacion temprana.
18. Saad, Y. - Iterative Methods for Sparse Linear Systems. Krylov, CG, precondicionadores.
19. Golub, G. H. y Van Loan, C. F. - Matrix Computations. Base obligatoria.
20. Hutchinson, M. F. - stochastic trace/diagonal estimators. Base para incertidumbre aproximada.
21. Bekas, Kokiopoulou y Saad - Estimation of the diagonal of matrix inverse. Relevante para posterior diag.
22. Halko, Martinsson y Tropp - Randomized numerical linear algebra. Util para rank approximation y uncertainty scalable.

### 6.4 Arquitectura SaaS/HPC geocientifica

23. Cockett, Kang, Heagy, Pidlisecky y Oldenburg (2015) - SimPEG: open-source framework. Arquitectura cientifica modular.
24. SimPEG/discretize docs - OcTree, TensorMesh, mappings, regularization, joint inversions.
25. Apache Arrow / Parquet / GeoParquet - transporte columnar binario y interoperabilidad.
26. Zarr / TileDB - arrays chunked out-of-core para volumetria.
27. Dask / Ray - ejecucion distribuida Python para workloads cientificos.
28. Kubernetes Jobs / Argo / Temporal - orquestacion de corridas largas.
29. OpenTelemetry + Prometheus - observabilidad de jobs numericos.
30. Cloud object storage design patterns - manifests inmutables, checksums, versioning y lifecycle.

## Fuentes externas verificadas

- Seequent Oasis montaj: https://www.seequent.com/products-solutions/oasis-montaj/
- Seequent VOXI Earth Modelling for Potential Fields: https://files.seequent.com/MySeequent/technical-notes/VOXI_Earth_Modelling_for_Potential_Fields.pdf
- VOXI brochure: https://files.seequent.com/PDFs/Oasis-montaj-VOXI.pdf
- SimPEG: https://simpeg.xyz/
- SimPEG joint inversion tutorial: https://docs.simpeg.xyz/latest/content/user-guide/tutorials/13-joint_inversion/index.html
- Seequent Central: https://www.seequent.com/products-solutions/seequent-central/
- Datamine Studio RM documentation: https://docs.dataminesoftware.com/StudioRM/
- SLB Software / Delfi: https://www.slb.com/products-and-services/delivering-digital-at-scale/software
- Google Gemini API deprecations: https://ai.google.dev/gemini-api/docs/deprecations
- Li & Oldenburg 1998 gravity inversion PDF: https://gif.eos.ubc.ca/sites/default/files/Li_1998a.pdf
- Li & Oldenburg 1996 magnetic inversion record: https://cir.nii.ac.jp/crid/1360845539090830720?lang=en
- Paige & Saunders LSQR PDF: https://web.stanford.edu/class/cme324/paige-saunders2.pdf

## Cierre CTO

TerraQuantum V2 tiene una semilla potente: combina inversion fisica, visualizacion web y narrativa IA con una preocupacion real por compliance. Eso es raro y valioso. Pero la industria minera no compra semillas; compra sistemas que sobreviven datos feos, coordenadas ambiguas, topografia hostil, consultores escépticos, auditorias legales, GPUs mediocres, internet lento, datasets gigantes y geofisicos que preguntan exactamente que hizo el software con cada observacion.

Hoy TerraQuantum todavia no sobrevive todo eso. Puede llegar. El camino no es decorar la UI ni prometer "IA minera". El camino es convertir cada afirmacion en un artefacto trazable, cada voxel en una entidad auditable, cada inversion en un experimento reproducible y cada reporte en una interpretacion limitada por fisica real.

Mi recomendacion estrategica: vender V2 solo como piloto de investigacion asistida, nunca como herramienta de decision. Construir V3 como plataforma de inversion geofisica auditable y cloud-native. Y proteger obsesivamente la frase mas importante del producto: esto prioriza honestidad tecnica, no certezas falsas.
