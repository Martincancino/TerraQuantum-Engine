"""
Umbrales de aceptacion ANCLADOS A MEDICION — barrido del 2026-08-06.

GENERADO, no escrito a mano (scratchpad/gen_acceptance.py). Fuente: 75 corridas
del brazo `s_strict_L2` (15 regimenes x 5 semillas), version de TQ `adba2b8+dirty`,
malla 18x14x18 @ 125 m, configuracion de PRODUCCION (Morozov con sigma declarado),
datos generados con `choclo` (anti-inverse-crime).

QUE CERTIFICAN Y QUE NO — leer antes de usarlos:
  * Son un gate de NO-REGRESION: fallan si una version futura empeora respecto de
    lo medido el 2026-08-06. NO certifican que el resultado sea bueno.
  * Los regimenes con PR-AUC mediano < 0.3 estan marcados RECUPERA=False:
    ahi el sistema NO recupera el cuerpo, y el umbral solo detecta cambios.
    Usarlos como prueba de calidad seria deshonesto.
  * Regla de umbral, declarada: error -> peor semilla x 1.25 ; pr_auc -> mejor
    dicho, minimo de las semillas x 0.75. Con n=5 el extremo observado no es el
    extremo poblacional; el margen de 25% absorbe ruido de semilla.
  * SOLO valen para el brazo `s_strict_L2`. El brazo permisivo hunde la masa al
    fondo en los 15 regimenes de esta malla y no tiene umbrales.

LIMITACION CONOCIDA — declararla vale mas que taparla:
  `Acceptance` se evalua sobre UNA corrida, asi que el umbral tiene que dar cabida
  a la peor semilla o fallaria contra una version sana. Y la distribucion medida es
  BIMODAL, no ancha: en `baseline` tres semillas dan PR-AUC 1.000 con 6-18 m de error
  y dos se desploman a 208-285 m. Resultado: el umbral por corrida (<=360 m) solo
  caza regresiones catastroficas. El gate afilado es la MEDIANA sobre N semillas,
  que se publica aqui en `MEDIANS` pero que el contrato todavia no sabe evaluar:
  hace falta una aceptacion de nivel AGREGADO. Es trabajo pendiente, no un descuido.
"""
from __future__ import annotations

from .contract import Acceptance, Threshold

ACCEPTANCE_SCHEMA = "acceptance/1"
MEASURED_ON = "barrido 2026-08-06 · 75 corridas · TQ adba2b8+dirty · brazo s_strict_L2"
QUALITY_PR_AUC = 0.3

BY_REGIME: dict[str, Acceptance] = {}
RECUPERA: dict[str, bool] = {}

# Medianas medidas sobre 5 semillas. Son el gate AFILADO (ver limitacion arriba):
# estables frente al ruido de semilla, a diferencia del extremo. Publicadas para
# que una aceptacion de nivel agregado pueda usarlas cuando exista.
MEDIANS: dict[str, dict[str, float]] = {
    "baseline": {"horizontal_error_m": 18.15, "depth_error_centroid_m": 89.89, "pr_auc": 1.000},
    "depth_250m": {"horizontal_error_m": 11.31, "depth_error_centroid_m": 20.08, "pr_auc": 1.000},
    "depth_400m": {"horizontal_error_m": 18.15, "depth_error_centroid_m": 89.89, "pr_auc": 1.000},
    "depth_600m": {"horizontal_error_m": 795.76, "depth_error_centroid_m": 1064.71, "pr_auc": 0.100},
    "depth_900m": {"horizontal_error_m": 277.69, "depth_error_centroid_m": 708.77, "pr_auc": 0.002},
    "coverage_14": {"horizontal_error_m": 53.40, "depth_error_centroid_m": 113.59, "pr_auc": 1.000},
    "coverage_9": {"horizontal_error_m": 95.17, "depth_error_centroid_m": 189.18, "pr_auc": 0.716},
    "coverage_6": {"horizontal_error_m": 675.36, "depth_error_centroid_m": 1231.75, "pr_auc": 0.225},
    "contrast_0.4": {"horizontal_error_m": 111.61, "depth_error_centroid_m": 178.86, "pr_auc": 0.716},
    "contrast_0.2": {"horizontal_error_m": 670.64, "depth_error_centroid_m": 430.42, "pr_auc": 0.273},
    "noise_0.05": {"horizontal_error_m": 418.40, "depth_error_centroid_m": 462.17, "pr_auc": 0.457},
    "noise_0.15": {"horizontal_error_m": 964.00, "depth_error_centroid_m": 1216.91, "pr_auc": 0.010},
    "span_1200m": {"horizontal_error_m": 1414.21, "depth_error_centroid_m": 1287.50, "pr_auc": 0.039},
    "span_800m": {"horizontal_error_m": 377.99, "depth_error_centroid_m": 1034.98, "pr_auc": 0.026},
    "worst_ldm_like": {"horizontal_error_m": 731.50, "depth_error_centroid_m": 617.58, "pr_auc": 0.002},
}

# --------------------------------------------------------------------------
# baseline  (w_base)   n=5 semillas
#   mediana medida: horizontal 18.2 m | profundidad 89.9 m | PR-AUC 1.000
#   RECUPERA: el umbral certifica que no se degrada una recuperacion que hoy funciona.
RECUPERA["baseline"] = True
BY_REGIME["baseline"] = Acceptance(
    schema_version=ACCEPTANCE_SCHEMA,
    applies_to="w_base",
    thresholds=(
        Threshold(metric="horizontal_error_m", op="<=", value=360.0,
                  justification=("Medido en el barrido 2026-08-06 sobre 5 semillas: mediana 18.152, extremo 285.511. Umbral = extremo x 1.25 (regla declarada en el docstring). Gate de NO-REGRESION. RECUPERA: el umbral certifica que no se degrada una recuperacion que hoy funciona."),
                  measured_on=MEASURED_ON, measured_value=18.1523),
        Threshold(metric="depth_error_centroid_m", op="<=", value=400.0,
                  justification=("Medido en el barrido 2026-08-06 sobre 5 semillas: mediana 89.890, extremo 315.314. Umbral = extremo x 1.25 (regla declarada en el docstring). Gate de NO-REGRESION. RECUPERA: el umbral certifica que no se degrada una recuperacion que hoy funciona."),
                  measured_on=MEASURED_ON, measured_value=89.8897),
        Threshold(metric="pr_auc", op=">=", value=0.437,
                  justification=("Medido en el barrido 2026-08-06 sobre 5 semillas: mediana 1.000, extremo 0.583. Umbral = extremo x 0.75 (regla declarada en el docstring). Gate de NO-REGRESION. RECUPERA: el umbral certifica que no se degrada una recuperacion que hoy funciona."),
                  measured_on=MEASURED_ON, measured_value=1.0000),
    ),
)

# --------------------------------------------------------------------------
# depth_250m  (w_depth_250)   n=5 semillas
#   mediana medida: horizontal 11.3 m | profundidad 20.1 m | PR-AUC 1.000
#   RECUPERA: el umbral certifica que no se degrada una recuperacion que hoy funciona.
RECUPERA["depth_250m"] = True
BY_REGIME["depth_250m"] = Acceptance(
    schema_version=ACCEPTANCE_SCHEMA,
    applies_to="w_depth_250",
    thresholds=(
        Threshold(metric="horizontal_error_m", op="<=", value=110.0,
                  justification=("Medido en el barrido 2026-08-06 sobre 5 semillas: mediana 11.309, extremo 80.511. Umbral = extremo x 1.25 (regla declarada en el docstring). Gate de NO-REGRESION. RECUPERA: el umbral certifica que no se degrada una recuperacion que hoy funciona."),
                  measured_on=MEASURED_ON, measured_value=11.3086),
        Threshold(metric="depth_error_centroid_m", op="<=", value=90.0,
                  justification=("Medido en el barrido 2026-08-06 sobre 5 semillas: mediana 20.075, extremo 64.838. Umbral = extremo x 1.25 (regla declarada en el docstring). Gate de NO-REGRESION. RECUPERA: el umbral certifica que no se degrada una recuperacion que hoy funciona."),
                  measured_on=MEASURED_ON, measured_value=20.0750),
        Threshold(metric="pr_auc", op=">=", value=0.546,
                  justification=("Medido en el barrido 2026-08-06 sobre 5 semillas: mediana 1.000, extremo 0.729. Umbral = extremo x 0.75 (regla declarada en el docstring). Gate de NO-REGRESION. RECUPERA: el umbral certifica que no se degrada una recuperacion que hoy funciona."),
                  measured_on=MEASURED_ON, measured_value=1.0000),
    ),
)

# --------------------------------------------------------------------------
# depth_400m  (w_depth_400)   n=5 semillas
#   mediana medida: horizontal 18.2 m | profundidad 89.9 m | PR-AUC 1.000
#   RECUPERA: el umbral certifica que no se degrada una recuperacion que hoy funciona.
RECUPERA["depth_400m"] = True
BY_REGIME["depth_400m"] = Acceptance(
    schema_version=ACCEPTANCE_SCHEMA,
    applies_to="w_depth_400",
    thresholds=(
        Threshold(metric="horizontal_error_m", op="<=", value=360.0,
                  justification=("Medido en el barrido 2026-08-06 sobre 5 semillas: mediana 18.152, extremo 285.511. Umbral = extremo x 1.25 (regla declarada en el docstring). Gate de NO-REGRESION. RECUPERA: el umbral certifica que no se degrada una recuperacion que hoy funciona."),
                  measured_on=MEASURED_ON, measured_value=18.1523),
        Threshold(metric="depth_error_centroid_m", op="<=", value=400.0,
                  justification=("Medido en el barrido 2026-08-06 sobre 5 semillas: mediana 89.890, extremo 315.314. Umbral = extremo x 1.25 (regla declarada en el docstring). Gate de NO-REGRESION. RECUPERA: el umbral certifica que no se degrada una recuperacion que hoy funciona."),
                  measured_on=MEASURED_ON, measured_value=89.8897),
        Threshold(metric="pr_auc", op=">=", value=0.437,
                  justification=("Medido en el barrido 2026-08-06 sobre 5 semillas: mediana 1.000, extremo 0.583. Umbral = extremo x 0.75 (regla declarada en el docstring). Gate de NO-REGRESION. RECUPERA: el umbral certifica que no se degrada una recuperacion que hoy funciona."),
                  measured_on=MEASURED_ON, measured_value=1.0000),
    ),
)

# --------------------------------------------------------------------------
# depth_600m  (w_depth_600)   n=5 semillas
#   mediana medida: horizontal 795.8 m | profundidad 1064.7 m | PR-AUC 0.100
#   NO RECUPERA en esta malla: el umbral SOLO detecta cambios, no certifica calidad.
RECUPERA["depth_600m"] = False
BY_REGIME["depth_600m"] = Acceptance(
    schema_version=ACCEPTANCE_SCHEMA,
    applies_to="w_depth_600",
    thresholds=(
        Threshold(metric="horizontal_error_m", op="<=", value=1200.0,
                  justification=("Medido en el barrido 2026-08-06 sobre 5 semillas: mediana 795.761, extremo 956.688. Umbral = extremo x 1.25 (regla declarada en el docstring). Gate de NO-REGRESION. NO RECUPERA en esta malla: el umbral SOLO detecta cambios, no certifica calidad."),
                  measured_on=MEASURED_ON, measured_value=795.7609),
        Threshold(metric="depth_error_centroid_m", op="<=", value=1350.0,
                  justification=("Medido en el barrido 2026-08-06 sobre 5 semillas: mediana 1064.714, extremo 1074.559. Umbral = extremo x 1.25 (regla declarada en el docstring). Gate de NO-REGRESION. NO RECUPERA en esta malla: el umbral SOLO detecta cambios, no certifica calidad."),
                  measured_on=MEASURED_ON, measured_value=1064.7142),
        Threshold(metric="pr_auc", op=">=", value=0.055,
                  justification=("Medido en el barrido 2026-08-06 sobre 5 semillas: mediana 0.100, extremo 0.074. Umbral = extremo x 0.75 (regla declarada en el docstring). Gate de NO-REGRESION. NO RECUPERA en esta malla: el umbral SOLO detecta cambios, no certifica calidad."),
                  measured_on=MEASURED_ON, measured_value=0.1005),
    ),
)

# --------------------------------------------------------------------------
# depth_900m  (w_depth_900)   n=5 semillas
#   mediana medida: horizontal 277.7 m | profundidad 708.8 m | PR-AUC 0.002
#   NO RECUPERA en esta malla: el umbral SOLO detecta cambios, no certifica calidad.
RECUPERA["depth_900m"] = False
BY_REGIME["depth_900m"] = Acceptance(
    schema_version=ACCEPTANCE_SCHEMA,
    applies_to="w_depth_900",
    thresholds=(
        Threshold(metric="horizontal_error_m", op="<=", value=680.0,
                  justification=("Medido en el barrido 2026-08-06 sobre 5 semillas: mediana 277.685, extremo 540.274. Umbral = extremo x 1.25 (regla declarada en el docstring). Gate de NO-REGRESION. NO RECUPERA en esta malla: el umbral SOLO detecta cambios, no certifica calidad."),
                  measured_on=MEASURED_ON, measured_value=277.6854),
        Threshold(metric="depth_error_centroid_m", op="<=", value=920.0,
                  justification=("Medido en el barrido 2026-08-06 sobre 5 semillas: mediana 708.774, extremo 728.178. Umbral = extremo x 1.25 (regla declarada en el docstring). Gate de NO-REGRESION. NO RECUPERA en esta malla: el umbral SOLO detecta cambios, no certifica calidad."),
                  measured_on=MEASURED_ON, measured_value=708.7741),
        Threshold(metric="pr_auc", op=">=", value=0.001,
                  justification=("Medido en el barrido 2026-08-06 sobre 5 semillas: mediana 0.002, extremo 0.002. Umbral = extremo x 0.75 (regla declarada en el docstring). Gate de NO-REGRESION. NO RECUPERA en esta malla: el umbral SOLO detecta cambios, no certifica calidad."),
                  measured_on=MEASURED_ON, measured_value=0.0025),
    ),
)

# --------------------------------------------------------------------------
# coverage_14  (w_base)   n=5 semillas
#   mediana medida: horizontal 53.4 m | profundidad 113.6 m | PR-AUC 1.000
#   RECUPERA: el umbral certifica que no se degrada una recuperacion que hoy funciona.
RECUPERA["coverage_14"] = True
BY_REGIME["coverage_14"] = Acceptance(
    schema_version=ACCEPTANCE_SCHEMA,
    applies_to="w_base",
    thresholds=(
        Threshold(metric="horizontal_error_m", op="<=", value=110.0,
                  justification=("Medido en el barrido 2026-08-06 sobre 5 semillas: mediana 53.399, extremo 83.428. Umbral = extremo x 1.25 (regla declarada en el docstring). Gate de NO-REGRESION. RECUPERA: el umbral certifica que no se degrada una recuperacion que hoy funciona."),
                  measured_on=MEASURED_ON, measured_value=53.3987),
        Threshold(metric="depth_error_centroid_m", op="<=", value=190.0,
                  justification=("Medido en el barrido 2026-08-06 sobre 5 semillas: mediana 113.594, extremo 149.341. Umbral = extremo x 1.25 (regla declarada en el docstring). Gate de NO-REGRESION. RECUPERA: el umbral certifica que no se degrada una recuperacion que hoy funciona."),
                  measured_on=MEASURED_ON, measured_value=113.5938),
        Threshold(metric="pr_auc", op=">=", value=0.536,
                  justification=("Medido en el barrido 2026-08-06 sobre 5 semillas: mediana 1.000, extremo 0.716. Umbral = extremo x 0.75 (regla declarada en el docstring). Gate de NO-REGRESION. RECUPERA: el umbral certifica que no se degrada una recuperacion que hoy funciona."),
                  measured_on=MEASURED_ON, measured_value=1.0000),
    ),
)

# --------------------------------------------------------------------------
# coverage_9  (w_base)   n=5 semillas
#   mediana medida: horizontal 95.2 m | profundidad 189.2 m | PR-AUC 0.716
#   RECUPERA: el umbral certifica que no se degrada una recuperacion que hoy funciona.
RECUPERA["coverage_9"] = True
BY_REGIME["coverage_9"] = Acceptance(
    schema_version=ACCEPTANCE_SCHEMA,
    applies_to="w_base",
    thresholds=(
        Threshold(metric="horizontal_error_m", op="<=", value=520.0,
                  justification=("Medido en el barrido 2026-08-06 sobre 5 semillas: mediana 95.167, extremo 410.785. Umbral = extremo x 1.25 (regla declarada en el docstring). Gate de NO-REGRESION. RECUPERA: el umbral certifica que no se degrada una recuperacion que hoy funciona."),
                  measured_on=MEASURED_ON, measured_value=95.1668),
        Threshold(metric="depth_error_centroid_m", op="<=", value=510.0,
                  justification=("Medido en el barrido 2026-08-06 sobre 5 semillas: mediana 189.182, extremo 407.106. Umbral = extremo x 1.25 (regla declarada en el docstring). Gate de NO-REGRESION. RECUPERA: el umbral certifica que no se degrada una recuperacion que hoy funciona."),
                  measured_on=MEASURED_ON, measured_value=189.1817),
        Threshold(metric="pr_auc", op=">=", value=0.283,
                  justification=("Medido en el barrido 2026-08-06 sobre 5 semillas: mediana 0.716, extremo 0.379. Umbral = extremo x 0.75 (regla declarada en el docstring). Gate de NO-REGRESION. RECUPERA: el umbral certifica que no se degrada una recuperacion que hoy funciona."),
                  measured_on=MEASURED_ON, measured_value=0.7158),
    ),
)

# --------------------------------------------------------------------------
# coverage_6  (w_base)   n=5 semillas
#   mediana medida: horizontal 675.4 m | profundidad 1231.8 m | PR-AUC 0.225
#   NO RECUPERA en esta malla: el umbral SOLO detecta cambios, no certifica calidad.
RECUPERA["coverage_6"] = False
BY_REGIME["coverage_6"] = Acceptance(
    schema_version=ACCEPTANCE_SCHEMA,
    applies_to="w_base",
    thresholds=(
        Threshold(metric="horizontal_error_m", op="<=", value=1500.0,
                  justification=("Medido en el barrido 2026-08-06 sobre 5 semillas: mediana 675.356, extremo 1194.266. Umbral = extremo x 1.25 (regla declarada en el docstring). Gate de NO-REGRESION. NO RECUPERA en esta malla: el umbral SOLO detecta cambios, no certifica calidad."),
                  measured_on=MEASURED_ON, measured_value=675.3561),
        Threshold(metric="depth_error_centroid_m", op="<=", value=1610.0,
                  justification=("Medido en el barrido 2026-08-06 sobre 5 semillas: mediana 1231.752, extremo 1287.500. Umbral = extremo x 1.25 (regla declarada en el docstring). Gate de NO-REGRESION. NO RECUPERA en esta malla: el umbral SOLO detecta cambios, no certifica calidad."),
                  measured_on=MEASURED_ON, measured_value=1231.7516),
        Threshold(metric="pr_auc", op=">=", value=0.118,
                  justification=("Medido en el barrido 2026-08-06 sobre 5 semillas: mediana 0.225, extremo 0.158. Umbral = extremo x 0.75 (regla declarada en el docstring). Gate de NO-REGRESION. NO RECUPERA en esta malla: el umbral SOLO detecta cambios, no certifica calidad."),
                  measured_on=MEASURED_ON, measured_value=0.2254),
    ),
)

# --------------------------------------------------------------------------
# contrast_0.4  (w_contrast_0.4)   n=5 semillas
#   mediana medida: horizontal 111.6 m | profundidad 178.9 m | PR-AUC 0.716
#   RECUPERA: el umbral certifica que no se degrada una recuperacion que hoy funciona.
RECUPERA["contrast_0.4"] = True
BY_REGIME["contrast_0.4"] = Acceptance(
    schema_version=ACCEPTANCE_SCHEMA,
    applies_to="w_contrast_0.4",
    thresholds=(
        Threshold(metric="horizontal_error_m", op="<=", value=900.0,
                  justification=("Medido en el barrido 2026-08-06 sobre 5 semillas: mediana 111.608, extremo 718.248. Umbral = extremo x 1.25 (regla declarada en el docstring). Gate de NO-REGRESION. RECUPERA: el umbral certifica que no se degrada una recuperacion que hoy funciona."),
                  measured_on=MEASURED_ON, measured_value=111.6085),
        Threshold(metric="depth_error_centroid_m", op="<=", value=910.0,
                  justification=("Medido en el barrido 2026-08-06 sobre 5 semillas: mediana 178.859, extremo 725.076. Umbral = extremo x 1.25 (regla declarada en el docstring). Gate de NO-REGRESION. RECUPERA: el umbral certifica que no se degrada una recuperacion que hoy funciona."),
                  measured_on=MEASURED_ON, measured_value=178.8590),
        Threshold(metric="pr_auc", op=">=", value=0.196,
                  justification=("Medido en el barrido 2026-08-06 sobre 5 semillas: mediana 0.716, extremo 0.262. Umbral = extremo x 0.75 (regla declarada en el docstring). Gate de NO-REGRESION. RECUPERA: el umbral certifica que no se degrada una recuperacion que hoy funciona."),
                  measured_on=MEASURED_ON, measured_value=0.7158),
    ),
)

# --------------------------------------------------------------------------
# contrast_0.2  (w_contrast_0.2)   n=5 semillas
#   mediana medida: horizontal 670.6 m | profundidad 430.4 m | PR-AUC 0.273
#   NO RECUPERA en esta malla: el umbral SOLO detecta cambios, no certifica calidad.
RECUPERA["contrast_0.2"] = False
BY_REGIME["contrast_0.2"] = Acceptance(
    schema_version=ACCEPTANCE_SCHEMA,
    applies_to="w_contrast_0.2",
    thresholds=(
        Threshold(metric="horizontal_error_m", op="<=", value=1610.0,
                  justification=("Medido en el barrido 2026-08-06 sobre 5 semillas: mediana 670.635, extremo 1282.408. Umbral = extremo x 1.25 (regla declarada en el docstring). Gate de NO-REGRESION. NO RECUPERA en esta malla: el umbral SOLO detecta cambios, no certifica calidad."),
                  measured_on=MEASURED_ON, measured_value=670.6354),
        Threshold(metric="depth_error_centroid_m", op="<=", value=1550.0,
                  justification=("Medido en el barrido 2026-08-06 sobre 5 semillas: mediana 430.423, extremo 1236.604. Umbral = extremo x 1.25 (regla declarada en el docstring). Gate de NO-REGRESION. NO RECUPERA en esta malla: el umbral SOLO detecta cambios, no certifica calidad."),
                  measured_on=MEASURED_ON, measured_value=430.4233),
        Threshold(metric="pr_auc", op=">=", value=0.127,
                  justification=("Medido en el barrido 2026-08-06 sobre 5 semillas: mediana 0.273, extremo 0.170. Umbral = extremo x 0.75 (regla declarada en el docstring). Gate de NO-REGRESION. NO RECUPERA en esta malla: el umbral SOLO detecta cambios, no certifica calidad."),
                  measured_on=MEASURED_ON, measured_value=0.2733),
    ),
)

# --------------------------------------------------------------------------
# noise_0.05  (w_base)   n=5 semillas
#   mediana medida: horizontal 418.4 m | profundidad 462.2 m | PR-AUC 0.457
#   RECUPERA: el umbral certifica que no se degrada una recuperacion que hoy funciona.
RECUPERA["noise_0.05"] = True
BY_REGIME["noise_0.05"] = Acceptance(
    schema_version=ACCEPTANCE_SCHEMA,
    applies_to="w_base",
    thresholds=(
        Threshold(metric="horizontal_error_m", op="<=", value=1610.0,
                  justification=("Medido en el barrido 2026-08-06 sobre 5 semillas: mediana 418.403, extremo 1281.264. Umbral = extremo x 1.25 (regla declarada en el docstring). Gate de NO-REGRESION. RECUPERA: el umbral certifica que no se degrada una recuperacion que hoy funciona."),
                  measured_on=MEASURED_ON, measured_value=418.4027),
        Threshold(metric="depth_error_centroid_m", op="<=", value=1550.0,
                  justification=("Medido en el barrido 2026-08-06 sobre 5 semillas: mediana 462.172, extremo 1237.672. Umbral = extremo x 1.25 (regla declarada en el docstring). Gate de NO-REGRESION. RECUPERA: el umbral certifica que no se degrada una recuperacion que hoy funciona."),
                  measured_on=MEASURED_ON, measured_value=462.1716),
        Threshold(metric="pr_auc", op=">=", value=0.138,
                  justification=("Medido en el barrido 2026-08-06 sobre 5 semillas: mediana 0.457, extremo 0.184. Umbral = extremo x 0.75 (regla declarada en el docstring). Gate de NO-REGRESION. RECUPERA: el umbral certifica que no se degrada una recuperacion que hoy funciona."),
                  measured_on=MEASURED_ON, measured_value=0.4572),
    ),
)

# --------------------------------------------------------------------------
# noise_0.15  (w_base)   n=5 semillas
#   mediana medida: horizontal 964.0 m | profundidad 1216.9 m | PR-AUC 0.010
#   NO RECUPERA en esta malla: el umbral SOLO detecta cambios, no certifica calidad.
RECUPERA["noise_0.15"] = False
BY_REGIME["noise_0.15"] = Acceptance(
    schema_version=ACCEPTANCE_SCHEMA,
    applies_to="w_base",
    thresholds=(
        Threshold(metric="horizontal_error_m", op="<=", value=1400.0,
                  justification=("Medido en el barrido 2026-08-06 sobre 5 semillas: mediana 963.998, extremo 1118.270. Umbral = extremo x 1.25 (regla declarada en el docstring). Gate de NO-REGRESION. NO RECUPERA en esta malla: el umbral SOLO detecta cambios, no certifica calidad."),
                  measured_on=MEASURED_ON, measured_value=963.9978),
        Threshold(metric="depth_error_centroid_m", op="<=", value=1580.0,
                  justification=("Medido en el barrido 2026-08-06 sobre 5 semillas: mediana 1216.908, extremo 1261.434. Umbral = extremo x 1.25 (regla declarada en el docstring). Gate de NO-REGRESION. NO RECUPERA en esta malla: el umbral SOLO detecta cambios, no certifica calidad."),
                  measured_on=MEASURED_ON, measured_value=1216.9081),
        Threshold(metric="pr_auc", op=">=", value=0.003,
                  justification=("Medido en el barrido 2026-08-06 sobre 5 semillas: mediana 0.010, extremo 0.005. Umbral = extremo x 0.75 (regla declarada en el docstring). Gate de NO-REGRESION. NO RECUPERA en esta malla: el umbral SOLO detecta cambios, no certifica calidad."),
                  measured_on=MEASURED_ON, measured_value=0.0097),
    ),
)

# --------------------------------------------------------------------------
# span_1200m  (w_base)   n=5 semillas
#   mediana medida: horizontal 1414.2 m | profundidad 1287.5 m | PR-AUC 0.039
#   NO RECUPERA en esta malla: el umbral SOLO detecta cambios, no certifica calidad.
RECUPERA["span_1200m"] = False
BY_REGIME["span_1200m"] = Acceptance(
    schema_version=ACCEPTANCE_SCHEMA,
    applies_to="w_base",
    thresholds=(
        Threshold(metric="horizontal_error_m", op="<=", value=1770.0,
                  justification=("Medido en el barrido 2026-08-06 sobre 5 semillas: mediana 1414.214, extremo 1414.214. Umbral = extremo x 1.25 (regla declarada en el docstring). Gate de NO-REGRESION. NO RECUPERA en esta malla: el umbral SOLO detecta cambios, no certifica calidad."),
                  measured_on=MEASURED_ON, measured_value=1414.2136),
        Threshold(metric="depth_error_centroid_m", op="<=", value=1610.0,
                  justification=("Medido en el barrido 2026-08-06 sobre 5 semillas: mediana 1287.500, extremo 1287.500. Umbral = extremo x 1.25 (regla declarada en el docstring). Gate de NO-REGRESION. NO RECUPERA en esta malla: el umbral SOLO detecta cambios, no certifica calidad."),
                  measured_on=MEASURED_ON, measured_value=1287.5000),
        Threshold(metric="pr_auc", op=">=", value=0.026,
                  justification=("Medido en el barrido 2026-08-06 sobre 5 semillas: mediana 0.039, extremo 0.035. Umbral = extremo x 0.75 (regla declarada en el docstring). Gate de NO-REGRESION. NO RECUPERA en esta malla: el umbral SOLO detecta cambios, no certifica calidad."),
                  measured_on=MEASURED_ON, measured_value=0.0395),
    ),
)

# --------------------------------------------------------------------------
# span_800m  (w_base)   n=5 semillas
#   mediana medida: horizontal 378.0 m | profundidad 1035.0 m | PR-AUC 0.026
#   NO RECUPERA en esta malla: el umbral SOLO detecta cambios, no certifica calidad.
RECUPERA["span_800m"] = False
BY_REGIME["span_800m"] = Acceptance(
    schema_version=ACCEPTANCE_SCHEMA,
    applies_to="w_base",
    thresholds=(
        Threshold(metric="horizontal_error_m", op="<=", value=1020.0,
                  justification=("Medido en el barrido 2026-08-06 sobre 5 semillas: mediana 377.989, extremo 814.900. Umbral = extremo x 1.25 (regla declarada en el docstring). Gate de NO-REGRESION. NO RECUPERA en esta malla: el umbral SOLO detecta cambios, no certifica calidad."),
                  measured_on=MEASURED_ON, measured_value=377.9892),
        Threshold(metric="depth_error_centroid_m", op="<=", value=1300.0,
                  justification=("Medido en el barrido 2026-08-06 sobre 5 semillas: mediana 1034.980, extremo 1037.500. Umbral = extremo x 1.25 (regla declarada en el docstring). Gate de NO-REGRESION. NO RECUPERA en esta malla: el umbral SOLO detecta cambios, no certifica calidad."),
                  measured_on=MEASURED_ON, measured_value=1034.9801),
        Threshold(metric="pr_auc", op=">=", value=0.018,
                  justification=("Medido en el barrido 2026-08-06 sobre 5 semillas: mediana 0.026, extremo 0.025. Umbral = extremo x 0.75 (regla declarada en el docstring). Gate de NO-REGRESION. NO RECUPERA en esta malla: el umbral SOLO detecta cambios, no certifica calidad."),
                  measured_on=MEASURED_ON, measured_value=0.0255),
    ),
)

# --------------------------------------------------------------------------
# worst_ldm_like  (w_depth_900)   n=5 semillas
#   mediana medida: horizontal 731.5 m | profundidad 617.6 m | PR-AUC 0.002
#   NO RECUPERA en esta malla: el umbral SOLO detecta cambios, no certifica calidad.
RECUPERA["worst_ldm_like"] = False
BY_REGIME["worst_ldm_like"] = Acceptance(
    schema_version=ACCEPTANCE_SCHEMA,
    applies_to="w_depth_900",
    thresholds=(
        Threshold(metric="horizontal_error_m", op="<=", value=1090.0,
                  justification=("Medido en el barrido 2026-08-06 sobre 5 semillas: mediana 731.505, extremo 870.375. Umbral = extremo x 1.25 (regla declarada en el docstring). Gate de NO-REGRESION. NO RECUPERA en esta malla: el umbral SOLO detecta cambios, no certifica calidad."),
                  measured_on=MEASURED_ON, measured_value=731.5049),
        Threshold(metric="depth_error_centroid_m", op="<=", value=830.0,
                  justification=("Medido en el barrido 2026-08-06 sobre 5 semillas: mediana 617.584, extremo 661.854. Umbral = extremo x 1.25 (regla declarada en el docstring). Gate de NO-REGRESION. NO RECUPERA en esta malla: el umbral SOLO detecta cambios, no certifica calidad."),
                  measured_on=MEASURED_ON, measured_value=617.5842),
        Threshold(metric="pr_auc", op=">=", value=0.001,
                  justification=("Medido en el barrido 2026-08-06 sobre 5 semillas: mediana 0.002, extremo 0.002. Umbral = extremo x 0.75 (regla declarada en el docstring). Gate de NO-REGRESION. NO RECUPERA en esta malla: el umbral SOLO detecta cambios, no certifica calidad."),
                  measured_on=MEASURED_ON, measured_value=0.0023),
    ),
)


def for_regime(name: str) -> Acceptance:
    """Aceptacion medida del regimen. KeyError explicito si no fue medido (P3)."""
    if name not in BY_REGIME:
        raise KeyError(
            f"El regimen {name!r} no tiene umbrales medidos. No se puede gatear "
            f"contra un umbral inventado (P3). Regimenes medidos: {sorted(BY_REGIME)}")
    return BY_REGIME[name]
