"""FASE 23 — Error Handling + User Feedback Overhaul.

Jerarquía de excepciones + catálogo de errores accionables para TerraQuantum.

Principio rector (roadmap Fase 23): el usuario NUNCA recibe un error genérico.
Cada fallo trae:
  • code              — identificador estable, p.ej. "CSV_EMPTY" (lo consume el frontend)
  • severity          — "error" | "warning" | "info"
  • user_message      — texto en ESPAÑOL, descriptivo (>100 caracteres), sin jerga cruda
  • technical_details — dict con diagnósticos (cond(A), SNR, iteraciones, conteos…)
  • suggested_action  — pasos concretos en español para resolver el problema

El catálogo (`CATALOG`) es la fuente de verdad: 50+ entradas con plantillas de
mensaje y acción. Una excepción se construye con un `code` del catálogo y
opcionalmente contexto que rellena los placeholders ({snr}, {n}, {cond}…) y se
adjunta como `technical_details`.

Backward-compat: las subclases aceptan también un mensaje literal como primer
argumento (p.ej. `InsufficientDataError("Necesita …")`) para no romper las
llamadas existentes; `InsufficientDataError` además es `ValueError`.

Este módulo NO ejecuta física: es la capa de contrato de errores que envuelve a
servicios y endpoints. El frontend (modal de 3 pestañas RESUMEN/DETALLES/ACCIÓN)
consume `to_dict()`; el polling async consume `to_error_details()` (compatible con
`schemas.response_schema.ErrorDetails`).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, Optional

# Severidades válidas (alineadas con ErrorDetails / frontend).
SEVERITY_ERROR = "error"
SEVERITY_WARNING = "warning"
SEVERITY_INFO = "info"
_VALID_SEVERITIES = (SEVERITY_ERROR, SEVERITY_WARNING, SEVERITY_INFO)


@dataclass(frozen=True)
class ErrorSpec:
    """Plantilla de un error del catálogo. Los textos pueden traer placeholders
    con formato `str.format` ({snr}, {n}, …) que se rellenan con el contexto al
    construir la excepción."""

    code: str
    severity: str
    user_message: str
    suggested_action: str


# ─────────────────────────────────────────────────────────────────────────────
# CATÁLOGO DE ERRORES (50+). Todos los user_message en español y >100 caracteres
# (incluso tras rellenar placeholders). Cada uno propone una acción concreta.
# ─────────────────────────────────────────────────────────────────────────────

_SPECS = [
    # ── CSV: estructura y parseo ─────────────────────────────────────────────
    ErrorSpec(
        "CSV_EMPTY", SEVERITY_ERROR,
        "El archivo CSV que cargaste no contiene ninguna fila de datos: está "
        "completamente vacío o solo trae la cabecera. Sin observaciones no es "
        "posible plantear una inversión geofísica.",
        "Exporta de nuevo el CSV asegurándote de incluir al menos 5 estaciones "
        "con sus coordenadas y la lectura medida (g_obs o magnetic_nt), y vuelve "
        "a cargarlo.",
    ),
    ErrorSpec(
        "CSV_SINGLE_ROW", SEVERITY_ERROR,
        "El CSV tiene una sola fila de datos. Una inversión 3D necesita varias "
        "estaciones distribuidas en el área para resolver la geometría del cuerpo "
        "en profundidad; con un único punto el problema es indeterminado.",
        "Agrega más estaciones al levantamiento (mínimo 5, idealmente >20) con "
        "buena distribución espacial y vuelve a exportar el CSV.",
    ),
    ErrorSpec(
        "CSV_NOT_CSV_EXTENSION", SEVERITY_ERROR,
        "El archivo subido no termina en .csv. TerraQuantum espera un archivo de "
        "valores separados por comas (o punto y coma) con una fila de cabecera y "
        "una fila por estación medida.",
        "Guarda tus datos como .csv (en Excel: «Guardar como → CSV UTF-8») y "
        "vuelve a subir el archivo.",
    ),
    ErrorSpec(
        "CSV_NO_HEADER", SEVERITY_ERROR,
        "No se detectó una fila de cabecera con nombres de columna en el CSV. "
        "TerraQuantum identifica las columnas por su nombre (x, y, z, g_obs, "
        "magnetic_nt, lat, lon…) y sin cabecera no puede mapearlas.",
        "Agrega como primera fila los nombres de columna, por ejemplo: "
        "x,y,z,g_obs,sigma — y vuelve a cargar el archivo.",
    ),
    ErrorSpec(
        "CSV_WRONG_DELIMITER", SEVERITY_ERROR,
        "No se pudo separar el CSV en columnas: el delimitador detectado no "
        "coincide con el contenido (probablemente mezcla de comas, punto y coma o "
        "tabuladores). Todo el archivo se está leyendo como una sola columna.",
        "Reexporta el CSV con un único delimitador consistente (coma «,» o punto "
        "y coma «;») y vuelve a subirlo.",
    ),
    ErrorSpec(
        "CSV_MISSING_COLUMNS", SEVERITY_ERROR,
        "Faltan columnas obligatorias en el CSV: {missing}. Sin coordenadas y una "
        "lectura medida no es posible construir el kernel de sensibilidad ni "
        "plantear la inversión.",
        "Agrega las columnas faltantes ({missing}) con sus valores y vuelve a "
        "cargar el archivo. Revisa el manual para los nombres aceptados.",
    ),
    ErrorSpec(
        "CSV_EXTRA_COLUMNS", SEVERITY_WARNING,
        "El CSV trae columnas que TerraQuantum no reconoce y que serán ignoradas: "
        "{extra}. Esto no detiene el proceso, pero conviene confirmar que ninguna "
        "de ellas era en realidad un dato necesario mal nombrado.",
        "Revisa los nombres de columna: si alguna de {extra} debía ser g_obs, "
        "sigma o una coordenada, renómbrala según el formato esperado.",
    ),
    ErrorSpec(
        "CSV_SPECIAL_CHARACTERS", SEVERITY_WARNING,
        "Se encontraron caracteres no numéricos o símbolos especiales dentro de "
        "celdas que deberían ser numéricas (por ejemplo unidades pegadas al valor, "
        "comas decimales europeas o texto). Esos valores no se pudieron interpretar.",
        "Limpia las celdas afectadas dejando solo números (usa punto «.» como "
        "separador decimal y no incluyas unidades dentro de la celda) y recarga.",
    ),
    ErrorSpec(
        "CSV_ENCODING", SEVERITY_ERROR,
        "No se pudo decodificar el CSV: la codificación del archivo no es UTF-8 ni "
        "una variante reconocida, lo que corrompe los caracteres y los números. "
        "Esto suele pasar al exportar desde planillas en español con acentos.",
        "Vuelve a guardar el archivo como «CSV UTF-8» desde tu hoja de cálculo y "
        "súbelo nuevamente.",
    ),
    # ── CSV: contenido y calidad ─────────────────────────────────────────────
    ErrorSpec(
        "CSV_ALL_NAN", SEVERITY_ERROR,
        "Todas las lecturas de la columna medida son NaN (vacías o no numéricas). "
        "El archivo tiene filas, pero ninguna contiene un valor de gravedad o "
        "magnetismo aprovechable para la inversión.",
        "Revisa la columna de datos (g_obs / magnetic_nt): asegúrate de que "
        "contenga números reales y no celdas vacías, y vuelve a exportar el CSV.",
    ),
    ErrorSpec(
        "CSV_NAN_INF", SEVERITY_WARNING,
        "Se detectaron {n} valores no finitos (NaN o infinito) en columnas "
        "numéricas del CSV. Esas filas serán marcadas y no participarán en la "
        "inversión, pero conviene saber por qué quedaron sin medición.",
        "Inspecciona las {n} filas marcadas: complétalas con la lectura correcta o "
        "elimínalas si la estación no se midió, y vuelve a cargar el archivo.",
    ),
    ErrorSpec(
        "CSV_ZERO_RANGE", SEVERITY_WARNING,
        "La señal medida no tiene variación: todos los valores de la columna son "
        "prácticamente idénticos (rango ≈ 0). Sin contraste espacial no hay "
        "anomalía que invertir y el modelo resultante será plano.",
        "Verifica que estás usando la columna correcta y que el dato no fue "
        "constante-rellenado; recolecta mediciones con variación espacial real.",
    ),
    ErrorSpec(
        "CSV_DUPLICATE_100", SEVERITY_WARNING,
        "El CSV contiene un {pct}% de filas exactamente duplicadas (misma "
        "coordenada y misma lectura). Los duplicados no aportan información nueva y "
        "sesgan artificialmente el peso de esas estaciones en la inversión.",
        "Permite que TerraQuantum fusione los duplicados automáticamente, o "
        "elimínalos manualmente antes de recargar el archivo.",
    ),
    ErrorSpec(
        "CSV_DUPLICATE_PARTIAL", SEVERITY_INFO,
        "Se encontraron {n} estaciones con coordenadas repetidas pero lecturas "
        "distintas. Esto puede ser remediciones legítimas del mismo punto o un "
        "error de georreferenciación que conviene revisar.",
        "Si son remediciones del mismo punto, promédialas; si no, corrige las "
        "coordenadas para que cada estación tenga su ubicación real.",
    ),
    ErrorSpec(
        "CSV_UNKNOWN_TYPE", SEVERITY_ERROR,
        "No se pudo determinar automáticamente si el CSV es de gravimetría, "
        "magnetometría o sondajes: no se reconocieron columnas características "
        "(g_obs, magnetic_nt, depth_from…). El tipo de dato es ambiguo.",
        "Indica manualmente el tipo de dato en el formulario de carga, o renombra "
        "la columna de medición con un nombre estándar (g_obs, magnetic_nt).",
    ),
    ErrorSpec(
        "CSV_UNIT_UNKNOWN", SEVERITY_ERROR,
        "No se reconoció la unidad de la columna «{column}»: «{unit}». "
        "TerraQuantum necesita conocer la unidad para normalizar a mGal / metros / "
        "nT antes de invertir, y un valor mal interpretado escala todo el modelo.",
        "Especifica la unidad correcta de «{column}» en el formulario "
        "(mGal, Gal, m/s² para gravedad; m, ft, km para distancias).",
    ),
    # ── Datos insuficientes / geometría ──────────────────────────────────────
    ErrorSpec(
        "DATA_NO_MODALITY", SEVERITY_ERROR,
        "No hay datos mínimos para plantear una inversión: el levantamiento no "
        "incluye ni gravimetría ni magnetometría. Los sondajes por sí solos "
        "restringen densidades pero no pueden generar el modelo 3D inicial.",
        "Carga al menos una modalidad de campo potencial (gravimetría o "
        "magnetometría) con sus estaciones medidas y vuelve a intentarlo.",
    ),
    ErrorSpec(
        "DATA_TOO_FEW_SENSORS", SEVERITY_ERROR,
        "El levantamiento tiene solo {n} estaciones, por debajo del mínimo de {min} "
        "necesario para una inversión con sentido. Con tan pocos puntos el problema "
        "queda fuertemente indeterminado y el modelo no sería confiable.",
        "Densifica el levantamiento hasta al menos {min} estaciones (idealmente "
        ">20) con buena cobertura del área de interés y reintenta.",
    ),
    ErrorSpec(
        "DATA_TOO_FEW_OBSERVATIONS", SEVERITY_ERROR,
        "Tras descartar filas inválidas quedan solo {n} observaciones utilizables, "
        "insuficientes para resolver la inversión. Es posible que muchas estaciones "
        "hayan quedado fuera por valores no finitos o coordenadas faltantes.",
        "Revisa cuántas filas se descartaron y por qué; recupera las estaciones "
        "válidas completando coordenadas o lecturas, y vuelve a cargar el CSV.",
    ),
    ErrorSpec(
        "DATA_NO_COORDINATES", SEVERITY_ERROR,
        "Las estaciones no tienen coordenadas: faltan tanto lat/lon como UTM y "
        "tampoco hay coordenadas locales (x, y). Sin posición no se puede ubicar "
        "el levantamiento ni muestrear el DEM para la topografía de la malla.",
        "Agrega coordenadas por estación (lat/lon o easting/northing UTM). Los "
        "gravímetros y magnetómetros modernos las registran por GPS en cada lectura.",
    ),
    ErrorSpec(
        "DATA_COLLINEAR_SENSORS", SEVERITY_WARNING,
        "Las estaciones están prácticamente alineadas (colineales): forman una "
        "línea en vez de cubrir un área. Esto hace que la profundidad y la posición "
        "perpendicular al perfil queden mal resueltas en el modelo 3D.",
        "Complementa con estaciones fuera de la línea para lograr una distribución "
        "2D del área; o interpreta el resultado como un perfil 2D, no como un 3D.",
    ),
    ErrorSpec(
        "DATA_ZERO_HULL", SEVERITY_WARNING,
        "El área cubierta por las estaciones es prácticamente nula (todas en el "
        "mismo punto o sobre una línea). El indicador de distribución espacial cae "
        "a 0 y la inversión no podrá resolver geometría lateral.",
        "Verifica las coordenadas de las estaciones: deben estar repartidas en el "
        "área de prospección, no concentradas en un punto.",
    ),
    # ── Georreferenciación (Fase 19) ─────────────────────────────────────────
    ErrorSpec(
        "GEOREF_MISSING_ANCHOR", SEVERITY_WARNING,
        "Las coordenadas son locales/relativas (x, y) y no se entregó ningún punto "
        "de referencia con coordenadas reales. El modelo se construirá en sistema "
        "relativo, sin poder ubicarse sobre un mapa ni muestrear el DEM real.",
        "Aporta al menos 2 puntos de control con coordenadas UTM o lat/lon reales "
        "para resolver posición, rotación y escala (transformada de Helmert).",
    ),
    ErrorSpec(
        "GEOREF_SINGLE_ANCHOR_NO_AZIMUTH", SEVERITY_WARNING,
        "Solo se entregó un punto de anclaje para coordenadas locales. Un único "
        "punto fija la posición pero NO la rotación: el azimut del eje +x local "
        "queda supuesto, lo que puede orientar mal todo el modelo sobre el mapa.",
        "Entrega un segundo punto de control con coordenadas reales, o indica "
        "explícitamente el azimut (rumbo en grados) del eje +x local.",
    ),
    ErrorSpec(
        "GEOREF_HELMERT_HIGH_RESIDUAL", SEVERITY_WARNING,
        "La transformación de georreferenciación (Helmert) tiene un residual alto "
        "de {residual_m} m: las distancias entre puntos de control no se preservan "
        "bien. Esto indica puntos de referencia mal medidos o mal apareados.",
        "Revisa que los puntos de control correspondan a las estaciones correctas y "
        "que sus coordenadas reales sean exactas; corrígelos y vuelve a anclar.",
    ),
    ErrorSpec(
        "GEOREF_DATUM_MISMATCH", SEVERITY_WARNING,
        "Posible mezcla de datums verticales: las elevaciones de las estaciones "
        "parecen ser elipsoidales (GPS) y el DEM es ortométrico (geoide), o "
        "viceversa. Mezclarlos introduce un offset sistemático de hasta ~30 m.",
        "Unifica el datum vertical de estaciones y DEM (o aplica conversión EGM2008 "
        "h↔H). Confirma en el formulario qué datum trae cada fuente.",
    ),
    ErrorSpec(
        "GEOREF_UTM_ZONE_UNKNOWN", SEVERITY_WARNING,
        "No se pudo determinar la zona UTM del levantamiento a partir de las "
        "coordenadas. Sin la zona correcta la conversión lat/lon ↔ UTM puede "
        "desplazar el modelo cientos de metros respecto de su ubicación real.",
        "Confirma la zona UTM en el formulario de carga (por ejemplo 19S para el "
        "centro de Chile) antes de continuar con la inversión.",
    ),
    # ── Solver / inversión ───────────────────────────────────────────────────
    ErrorSpec(
        "SOLVER_DIVERGED_HIGH_NOISE", SEVERITY_ERROR,
        "La inversión no convergió porque los datos son muy ruidosos "
        "(SNR ≈ {snr}). El solver no puede separar la señal del ruido y el ajuste "
        "no baja al nivel esperado de error de medición.",
        "Filtra las estaciones con baja relación señal/ruido o con residuos "
        "extremos (>3σ), revisa la calibración del instrumento y vuelve a invertir.",
    ),
    ErrorSpec(
        "SOLVER_DIVERGED_ILL_CONDITIONED", SEVERITY_ERROR,
        "El sistema lineal de la inversión quedó mal condicionado "
        "(cond(A) ≈ {cond}): la geometría del levantamiento y la malla hacen el "
        "problema casi singular, por lo que la solución es inestable.",
        "Aumenta la regularización (λ) para estabilizar el sistema, reduce el "
        "tamaño de la malla respecto del área cubierta, o mejora la cobertura.",
    ),
    ErrorSpec(
        "SOLVER_MAX_ITER", SEVERITY_WARNING,
        "El solver alcanzó el máximo de {iters} iteraciones sin cumplir el criterio "
        "de convergencia (norma del gradiente {gnorm}). El resultado puede ser "
        "utilizable pero no está plenamente convergido.",
        "Aumenta el número máximo de iteraciones, sube ligeramente λ para acelerar "
        "la convergencia, o acepta el resultado parcial revisando el misfit.",
    ),
    ErrorSpec(
        "SOLVER_EMPTY_KERNEL", SEVERITY_ERROR,
        "El kernel de sensibilidad quedó vacío: no se generó ninguna relación entre "
        "las estaciones y las celdas de la malla. Suele deberse a una malla mal "
        "ubicada respecto del levantamiento o a parámetros de grilla incompatibles.",
        "Verifica que la malla (nx, ny, nz, tamaño de bloque) cubra el área de las "
        "estaciones y que las coordenadas estén en el mismo sistema; reintenta.",
    ),
    ErrorSpec(
        "SOLVER_NO_ACTIVE_VOXELS", SEVERITY_ERROR,
        "Tras aplicar la máscara de aire (topografía) no quedó ninguna celda activa "
        "bajo la superficie en la malla. Es probable que la elevación de la malla y "
        "la del DEM/estaciones estén en escalas o datums incompatibles.",
        "Revisa la consistencia de elevaciones entre estaciones, DEM y malla; "
        "ajusta la profundidad de la grilla para que haya volumen bajo el terreno.",
    ),
    ErrorSpec(
        "SOLVER_NAN_IN_RESULT", SEVERITY_ERROR,
        "La inversión produjo valores no finitos (NaN o infinito) en el modelo de "
        "densidad/susceptibilidad. Esto indica una inestabilidad numérica, "
        "típicamente por regularización demasiado baja o datos con valores extremos.",
        "Sube la regularización (λ), revisa que no queden outliers extremos en los "
        "datos y verifica las unidades; luego vuelve a ejecutar la inversión.",
    ),
    ErrorSpec(
        "SOLVER_GRID_TOO_LARGE", SEVERITY_ERROR,
        "La malla solicitada tiene {n_voxels} celdas, por encima del límite que el "
        "modo actual puede resolver en memoria. Una grilla enorme frente a un "
        "levantamiento pequeño además no mejora la resolución real.",
        "Reduce nx, ny o nz, o aumenta el tamaño de bloque para bajar el número de "
        "celdas; activa el modo out-of-core (Zarr) si necesitas la malla completa.",
    ),
    ErrorSpec(
        "SOLVER_REGIONAL_SCALE", SEVERITY_WARNING,
        "El área del levantamiento ({extent_km} km) excede la escala local validada "
        "de TerraQuantum (<50 km). A escala regional la ambigüedad de profundidad "
        "crece y el error esperado supera la métrica objetivo (<10–15 m).",
        "Para escala regional, restringe la interpretación a tendencias generales o "
        "subdivide el área en bloques locales; no uses el resultado para perforar.",
    ),
    # ── Sondajes (Fase 20) ───────────────────────────────────────────────────
    ErrorSpec(
        "BOREHOLE_CONFLICT", SEVERITY_WARNING,
        "Conflicto entre sondaje y modelo en {hole_id} a {depth} m: el sondaje mide "
        "densidad {rho_obs} t/m³ pero la inversión predice {rho_pred} t/m³. Una "
        "diferencia tan grande sugiere datos inconsistentes o heterogeneidad local.",
        "Verifica la densidad del testigo y su profundidad; si el sondaje es "
        "confiable, aumenta su peso como restricción (κ) y vuelve a invertir.",
    ),
    ErrorSpec(
        "BOREHOLE_DEPTH_REVERSED", SEVERITY_ERROR,
        "Un intervalo de sondaje tiene depth_to menor o igual que depth_from "
        "({d_from} → {d_to} m): el rango de profundidad está invertido o es nulo, lo "
        "que impide mapear el intervalo a celdas de la malla.",
        "Corrige las columnas depth_from/depth_to para que depth_to siempre sea "
        "mayor que depth_from en cada intervalo, y recarga el CSV de sondajes.",
    ),
    ErrorSpec(
        "BOREHOLE_OUT_OF_GRID", SEVERITY_WARNING,
        "El sondaje {hole_id} cae fuera de la malla de inversión: su ubicación o "
        "profundidad no intersecta ninguna celda activa. Sus mediciones no podrán "
        "usarse como restricción del modelo.",
        "Verifica las coordenadas del collar del sondaje y la extensión de la malla; "
        "amplía la grilla o corrige la georreferenciación del sondaje.",
    ),
    ErrorSpec(
        "BOREHOLE_MISSING_DENSITY", SEVERITY_WARNING,
        "El sondaje {hole_id} no trae densidad medida en uno o más intervalos. Sin "
        "densidad no puede anclar la inversión gravimétrica, aunque su litología sí "
        "puede informar los priors petrofísicos (PGI).",
        "Completa la densidad de los intervalos (downhole o de testigo) si la "
        "tienes; si solo hay litología, déjala para que aporte como prior PGI.",
    ),
    ErrorSpec(
        "BOREHOLE_DENSITY_OUT_OF_RANGE", SEVERITY_ERROR,
        "Una densidad de sondaje está fuera del rango físico plausible: {rho} t/m³ "
        "(se espera aproximadamente 0–10 t/m³). Un valor así suele ser un error de "
        "unidad (g/cm³ vs kg/m³) o un dato corrupto.",
        "Revisa la unidad de densidad del sondaje (debe estar en t/m³ ≈ g/cm³) y "
        "corrige el valor anómalo antes de recargar el archivo.",
    ),
    ErrorSpec(
        "BOREHOLE_NO_INTERVALS", SEVERITY_ERROR,
        "El CSV de sondajes no contiene ningún intervalo con al menos una propiedad "
        "medida (densidad o susceptibilidad). Un sondaje sin propiedades no aporta "
        "ninguna restricción a la inversión.",
        "Agrega al menos una columna de propiedad medida (density_t_m3 o "
        "susceptibility_si) con valores en los intervalos, y vuelve a cargar.",
    ),
    ErrorSpec(
        "BOREHOLE_UNIT_UNKNOWN", SEVERITY_ERROR,
        "No se reconoció la unidad de profundidad de los sondajes: «{unit}». Las "
        "profundidades deben convertirse a metros antes de mapearlas a la malla, y "
        "una unidad mal interpretada desplaza los intervalos en vertical.",
        "Indica la unidad de profundidad (m o ft). Recuerda que muchos sondajes "
        "históricos vienen en pies (ft) y deben convertirse a metros.",
    ),
    # ── Correcciones gravimétricas (Bloque B) ────────────────────────────────
    ErrorSpec(
        "CORRECTION_NO_ELEVATION", SEVERITY_WARNING,
        "No hay elevación por estación, así que no se pueden aplicar las "
        "correcciones de aire libre (FAC) ni de Bouguer, que dependen de la altura. "
        "La anomalía quedará sin estas reducciones estándar.",
        "Agrega la columna de elevación (msnm) por estación, o permite que "
        "TerraQuantum la complete muestreando el DEM de OpenTopography.",
    ),
    ErrorSpec(
        "CORRECTION_NO_LATLON", SEVERITY_WARNING,
        "No hay lat/lon por estación, por lo que no se puede calcular la gravedad "
        "teórica GRS80 (que depende de la latitud) ni la corrección de latitud. La "
        "anomalía se calculará sin esta reducción.",
        "Agrega coordenadas lat/lon por estación (o UTM con zona conocida) para "
        "habilitar la corrección GRS80 dependiente de la latitud.",
    ),
    ErrorSpec(
        "CORRECTION_TC_NEGATIVE", SEVERITY_ERROR,
        "La corrección de terreno resultó negativa en una o más estaciones, lo cual "
        "es físicamente imposible: la corrección topográfica siempre suma masa y "
        "debe ser ≥ 0. Indica un error en el DEM o en el cálculo.",
        "Revisa la calidad y el datum del DEM usado para la corrección de terreno; "
        "vuelve a descargar el DEM de la zona y reaplica la corrección.",
    ),
    ErrorSpec(
        "CORRECTION_DEM_UNAVAILABLE", SEVERITY_WARNING,
        "No se pudo obtener el DEM (modelo de elevación) desde OpenTopography: sin "
        "conexión, sin API key, o la zona no está cubierta. Se continuará sin "
        "corrección de terreno y la superficie de la malla usará método nearest.",
        "Verifica la conexión y la API key de OpenTopography, o carga manualmente "
        "las elevaciones por estación; el modelo seguirá con confianza reducida.",
    ),
    ErrorSpec(
        "CORRECTION_BOUGUER_DOUBLE_COUNT", SEVERITY_WARNING,
        "Se está aplicando la losa de Bouguer Y modelando la topografía en la malla "
        "a la vez. Existe riesgo de contar dos veces la masa del terreno, lo que "
        "sesgaría la geometría somera del modelo recuperado.",
        "Decide una sola estrategia: invertir el disturbio de aire libre con "
        "topografía en la malla (sin losa plana), o anomalía de Bouguer con "
        "máscara de aire. Documenta la elección.",
    ),
    # ── Multimodal (Fase 21) ─────────────────────────────────────────────────
    ErrorSpec(
        "MULTIMODAL_UNSUPPORTED_COMBO", SEVERITY_ERROR,
        "La combinación de datos entregada no corresponde a ninguna ruta de "
        "inversión soportada. Las rutas válidas son: gravimetría sola, "
        "magnetometría sola, grav+mag, grav+sondajes y todas juntas.",
        "Ajusta las modalidades cargadas a una combinación soportada; como mínimo "
        "incluye gravimetría o magnetometría con sus estaciones.",
    ),
    ErrorSpec(
        "MULTIMODAL_MISALIGNED", SEVERITY_WARNING,
        "Las grillas de gravimetría y magnetometría no están alineadas (distinta "
        "extensión, resolución u origen). La inversión conjunta necesita una malla "
        "común para acoplar ambas modalidades vía cross-gradient.",
        "Reproyecta ambos levantamientos a un sistema y zona UTM comunes; "
        "TerraQuantum construirá la malla core compartida automáticamente.",
    ),
    # ── Advertencias de calidad / convergencia (warnings/info) ───────────────
    ErrorSpec(
        "WARN_LOW_DATA_QUALITY", SEVERITY_WARNING,
        "La calidad de los datos es baja ({score}/100): combinación de cobertura "
        "limitada, ruido elevado y/o campos faltantes. El modelo resultante será "
        "menos confiable y su error de profundidad mayor de lo habitual.",
        "Mejora el levantamiento donde sea posible (más estaciones, mejor "
        "distribución, completar campos) o interpreta el modelo con cautela.",
    ),
    ErrorSpec(
        "WARN_SPARSE_SENSORS", SEVERITY_WARNING,
        "El levantamiento tiene pocas estaciones ({n}) para el área cubierta: la "
        "densidad de muestreo es baja y la resolución espacial del modelo quedará "
        "limitada, especialmente para cuerpos pequeños o profundos.",
        "Densifica el muestreo en las zonas de interés; cada estación adicional "
        "mejora directamente la resolución lateral del modelo.",
    ),
    ErrorSpec(
        "WARN_SLOW_CONVERGENCE", SEVERITY_INFO,
        "La inversión está convergiendo lentamente ({iters} iteraciones usadas). El "
        "resultado es válido, pero el solver necesitó muchas iteraciones para "
        "ajustar los datos, lo que suele indicar regularización algo baja.",
        "Si vuelves a ejecutar, subir ligeramente λ acelera la convergencia sin "
        "degradar el ajuste de forma apreciable.",
    ),
    ErrorSpec(
        "WARN_BOREHOLE_DISAGREEMENT", SEVERITY_WARNING,
        "Los sondajes sugieren densidades algo distintas a las del modelo "
        "(diferencia media {diff} t/m³, dentro de tolerancia pero no despreciable). "
        "Puede reflejar heterogeneidad real o un sesgo leve del modelo.",
        "Si confías en los sondajes, aumenta su peso como restricción; si son "
        "puntuales, considéralos como indicación local de heterogeneidad.",
    ),
    ErrorSpec(
        "WARN_HIGH_NOISE", SEVERITY_WARNING,
        "El nivel de ruido estimado en los datos es alto (σ ≈ {sigma}). La "
        "inversión puede continuar, pero parte de la variabilidad de la señal "
        "corresponde a ruido y no a estructura geológica real.",
        "Revisa la calibración del instrumento y filtra estaciones con residuos "
        "extremos; un sigma robusto (MAD) ya está mitigando los outliers.",
    ),
    ErrorSpec(
        "WARN_DEM_FALLBACK_NEAREST", SEVERITY_WARNING,
        "La superficie de la malla se construyó con la elevación del sensor más "
        "cercano (nearest), no con el DEM denso, porque el DEM no estaba "
        "disponible. En terreno rugoso esto produce una superficie escalonada.",
        "Habilita el DEM de OpenTopography (conexión + API key) para muestrear la "
        "topografía de la malla por columna y mejorar el error de profundidad.",
    ),
    ErrorSpec(
        "WARN_NEGATIVE_DENSITY_CLIP", SEVERITY_INFO,
        "Se aplicó un recorte de no-negatividad sobre el contraste de densidad: "
        "algunas celdas que tendían a valores negativos fueron limitadas. Esto "
        "puede degradar levemente el ajuste a cambio de un modelo más físico.",
        "Si esperas cavidades o déficits de masa reales (contraste negativo), "
        "desactiva el recorte de no-negatividad y vuelve a invertir.",
    ),
    ErrorSpec(
        "WARN_OUTLIERS_DETECTED", SEVERITY_INFO,
        "Se detectaron {n} posibles outliers en los datos mediante el criterio MAD "
        "(>3σ robusto). No se eliminaron automáticamente: la decisión es tuya, pero "
        "conviene revisarlos antes de invertir.",
        "Inspecciona las {n} estaciones marcadas y decide si fusionarlas, "
        "ignorarlas o eliminarlas; descárgalas con el botón de anomalías.",
    ),
    ErrorSpec(
        "INFO_UNITS_CONVERTED", SEVERITY_INFO,
        "Se normalizaron unidades automáticamente para la inversión: la columna "
        "«{column}» se convirtió de «{from_unit}» a «{to_unit}». El cálculo físico "
        "siempre trabaja en el sistema estándar (mGal, metros, nT).",
        "Confirma que la conversión de «{column}» es la esperada; si la unidad de "
        "origen era otra, corrígela en el formulario antes de continuar.",
    ),
    ErrorSpec(
        "INFO_ELEVATION_FROM_DEM", SEVERITY_INFO,
        "Faltaba la elevación de algunas estaciones y se completó automáticamente "
        "muestreando el DEM de OpenTopography. La elevación derivada del DEM tiene "
        "menos precisión que una medición GPS por estación.",
        "Para máxima precisión en el error de profundidad, mide la elevación por "
        "estación con GPS; la del DEM es un buen sustituto cuando no la tienes.",
    ),
    # ── Genérico / interno (fallback) ────────────────────────────────────────
    ErrorSpec(
        "TQ_INTERNAL", SEVERITY_ERROR,
        "Ocurrió un error interno inesperado en TerraQuantum mientras procesaba tu "
        "solicitud. El equipo registra estos casos con su detalle técnico para "
        "diagnosticarlos; tus datos no se perdieron.",
        "Reintenta la operación; si el problema persiste, descarga el registro de "
        "error y compártelo con soporte para una revisión detallada.",
    ),
]

# Índice por código (fuente de verdad para construir excepciones).
CATALOG: Dict[str, ErrorSpec] = {spec.code: spec for spec in _SPECS}


# ─────────────────────────────────────────────────────────────────────────────
# Jerarquía de excepciones
# ─────────────────────────────────────────────────────────────────────────────

class TerraquantumError(Exception):
    """Excepción base de TerraQuantum: siempre accionable, nunca genérica.

    Uso preferido (catálogo):
        raise SolverDivergenceError("SOLVER_DIVERGED_HIGH_NOISE", snr=0.08,
                                    technical_details={"cond": 2.3e12})

    Uso literal (backward-compat):
        raise InsufficientDataError("Necesita ≥ gravimetría o magnetometría.")

    Atributos:
        code, severity, user_message, suggested_action, technical_details
    """

    # Código por defecto cuando no se entrega uno del catálogo (lo sobreescriben
    # las subclases para dar un código sensato a los mensajes literales).
    default_code = "TQ_INTERNAL"
    default_severity = SEVERITY_ERROR

    def __init__(
        self,
        code: Optional[str] = None,
        *,
        message: Optional[str] = None,
        severity: Optional[str] = None,
        suggested_action: Optional[str] = None,
        technical_details: Optional[Dict[str, Any]] = None,
        **context: Any,
    ) -> None:
        spec = CATALOG.get(code) if isinstance(code, str) else None

        # Backward-compat: el primer argumento posicional es un mensaje literal
        # (no un código del catálogo) cuando no coincide con ninguna entrada y no
        # se pasó `message` por keyword.
        if spec is None and code is not None and message is None and severity is None:
            message = code
            code = None

        self.code = (code if spec else None) or (spec.code if spec else None) or self.default_code
        self.severity = severity or (spec.severity if spec else self.default_severity)
        if self.severity not in _VALID_SEVERITIES:
            self.severity = self.default_severity

        base_msg = message if message is not None else (
            spec.user_message if spec else "Error interno de TerraQuantum."
        )
        base_action = suggested_action if suggested_action is not None else (
            spec.suggested_action if spec else
            "Reintenta la operación; si persiste, contacta a soporte con el registro de error."
        )

        # Rellenar placeholders con el contexto. Si falta alguno, se deja el texto
        # base intacto (nunca rompemos por un placeholder ausente).
        self.user_message = _safe_format(base_msg, context)
        self.suggested_action = _safe_format(base_action, context)

        # El contexto también se conserva como detalle técnico para logs/diagnóstico.
        self.technical_details = dict(technical_details or {})
        for key, value in context.items():
            self.technical_details.setdefault(key, value)

        super().__init__(self.user_message)

    # ── Serialización ────────────────────────────────────────────────────────
    def to_dict(self) -> Dict[str, Any]:
        """Payload completo para el modal del frontend (3 pestañas)."""
        return {
            "code": self.code,
            "severity": self.severity,
            "user_message": self.user_message,
            "technical_details": self.technical_details,
            "suggested_action": self.suggested_action,
        }

    def to_error_details(
        self, source: Optional[str] = None, stage: Optional[str] = None
    ) -> Dict[str, Any]:
        """Payload compatible con `schemas.response_schema.ErrorDetails` (polling async)."""
        details = dict(self.technical_details)
        details["severity"] = self.severity
        details["suggested_action"] = self.suggested_action
        return {
            "code": self.code,
            "message": self.user_message,
            "source": source,
            "stage": stage,
            "details": details,
        }

    def __repr__(self) -> str:  # pragma: no cover - representación de depuración
        return f"{type(self).__name__}(code={self.code!r}, severity={self.severity!r})"


def _safe_format(template: str, context: Dict[str, Any]) -> str:
    """Aplica str.format con el contexto; ante placeholders faltantes devuelve el
    texto base sin romper (un error nunca debe fallar al construirse)."""
    if not context:
        return template
    try:
        return template.format(**context)
    except (KeyError, IndexError, ValueError):
        return template


class CsvValidationError(TerraquantumError):
    """Problema en el CSV de entrada (estructura, contenido, unidades)."""
    default_code = "CSV_EMPTY"


class InsufficientDataError(TerraquantumError, ValueError):
    """No hay datos mínimos para plantear una inversión.

    Subclasea también `ValueError` por compatibilidad: hay código que captura
    `ValueError` y tests/llamadas existentes que la instancian con un mensaje
    literal (`InsufficientDataError("…")`)."""
    default_code = "DATA_NO_MODALITY"


class SolverDivergenceError(TerraquantumError):
    """La inversión no convergió o produjo un resultado no finito."""
    default_code = "SOLVER_DIVERGED_HIGH_NOISE"


class ConflictingDataError(TerraquantumError):
    """Datos contradictorios entre modalidades (p.ej. sondaje vs modelo)."""
    default_code = "BOREHOLE_CONFLICT"


class GeoreferencingError(TerraquantumError):
    """Problema de georreferenciación que afecta la ubicación del modelo."""
    default_code = "GEOREF_MISSING_ANCHOR"


def get_spec(code: str) -> Optional[ErrorSpec]:
    """Devuelve la plantilla del catálogo para un código, o None si no existe."""
    return CATALOG.get(code)


__all__ = [
    "SEVERITY_ERROR",
    "SEVERITY_WARNING",
    "SEVERITY_INFO",
    "ErrorSpec",
    "CATALOG",
    "get_spec",
    "TerraquantumError",
    "CsvValidationError",
    "InsufficientDataError",
    "SolverDivergenceError",
    "ConflictingDataError",
    "GeoreferencingError",
]
