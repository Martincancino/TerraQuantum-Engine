"""
Inversion Postprocess Service — Fase 2 (Plan Industrial Tier 1, §2.1)

Módulo aislado con las funciones de post-procesamiento del modelo invertido:
construcción del block model, filtrado de anomalías y estimación de ley heurística.
Extraído de geophysics_service.py para separación de responsabilidades.
geophysics_service.py importa desde aquí y re-exporta para compatibilidad.
"""
import numpy as np
import polars as pl

from schemas.geophysics_schema import GeophysicsInvertInput


def estimate_grade_from_geophysics(
    density: np.ndarray,
    probability: np.ndarray,
    nir: int,
    fe: int,
    region: str,
):
    density_score = np.clip((density - 2.6) / max(4.2 - 2.6, 1e-9), 0.0, 1.0)
    probability_score = np.clip(probability, 0.0, 1.0)

    nir_score = np.clip(float(nir) / 100.0, 0.0, 1.0)
    fe_score = np.clip(float(fe) / 100.0, 0.0, 1.0)

    region_factor = {
        "norte_chile": 1.15,
        "andes_central": 1.08,
        "canada": 0.92,
        "desconocida": 1.0,
    }.get(str(region).lower().strip(), 1.0)

    raw_grade = (
        0.08
        + 1.85 * density_score
        + 1.15 * probability_score
        + 0.45 * nir_score
        + 0.35 * fe_score
    ) * region_factor

    # Los bloques realmente débiles quedan bajo cutoff.
    weak_mask = (density_score < 0.18) | (probability_score < 0.15)
    raw_grade = np.where(weak_mask, raw_grade * 0.18, raw_grade)

    return np.clip(raw_grade, 0.0, 5.0)


def build_full_block_model_dataframe(
    params: GeophysicsInvertInput,
    ix: np.ndarray,
    iy: np.ndarray,
    iz: np.ndarray,
    x_c: np.ndarray,
    y_c: np.ndarray,
    z_c: np.ndarray,
    est_density: np.ndarray,
    probability: np.ndarray,
    base_density: float = 2.6,
    cutoff_density: float = 2.75,
):
    dx = params.block_size

    density = np.asarray(est_density, dtype=float)
    probability = np.asarray(probability, dtype=float)

    # Máscara de celdas activas (NaN = celda de aire)
    is_active = np.isfinite(density) & np.isfinite(probability)

    # Usar valores seguros (0 para NaN) en cálculos escalares para evitar propagación
    density_safe = np.where(is_active, density, 0.0)
    probability_safe = np.where(is_active, probability, 0.0)

    # Integridad científica (gap #1): la "ley" (grade) es un proxy heurístico no físico.
    # Solo se fabrica en modo demo explícito (expose_demo_grade=True). Por defecto queda
    # como NaN → null en el payload; el contraste de densidad (física real) se conserva.
    if getattr(params, "expose_demo_grade", False):
        grade = estimate_grade_from_geophysics(
            density=density_safe,
            probability=probability_safe,
            nir=params.nir,
            fe=params.fe,
            region=params.region,
        )
        grade = np.where(is_active, grade, np.nan)
    else:
        grade = np.full(density.shape[0], np.nan, dtype=float)

    block_volume_m3 = float(dx * dx * dx)
    modeled_rock_mass_tonnes = np.where(is_active, density_safe * block_volume_m3, np.nan)

    density_score = np.clip((density_safe - 2.6) / max(4.2 - 2.6, 1e-9), 0.0, 1.0)
    probability_score = np.clip(probability_safe, 0.0, 1.0)
    visual_score = np.where(is_active, density_score * probability_score, np.nan)

    density_zone_flag = np.where(is_active & (density_safe >= 2.75), 1, 0).astype(int)

    density_confidence_tier = np.where(probability_score >= 0.7, 1, 2).astype(int)
    density_confidence_tier = np.where(probability_score < 0.35, 3, density_confidence_tier)
    density_confidence_tier = np.where(is_active, density_confidence_tier, 0).astype(int)

    # ── Schema v4.0: columnas unificadas ─────────────────────────────────────────
    # density_contrast_t_m3: contraste respecto a base_density (Li & Oldenburg 1998)
    density_contrast = np.where(is_active, density_safe - base_density, np.nan)
    # density_anomaly_score: [0,1] normalizado sobre cutoff_density
    _denom = max(float(cutoff_density), 1e-9)
    density_anomaly_score = np.where(
        is_active,
        np.clip((density_safe - cutoff_density) / _denom, 0.0, 1.0),
        np.nan,
    )

    df_full = pl.DataFrame(
        {
            # ── v3.0 legacy coords (backward compat) ─────────────────────────────
            "x": x_c.astype(float),
            "y": y_c.astype(float),
            "z": z_c.astype(float),
            # ── v4.0 unified coords ───────────────────────────────────────────────
            "x_m": x_c.astype(float),
            "y_m": y_c.astype(float),
            "z_m": z_c.astype(float),
            # ── indices ───────────────────────────────────────────────────────────
            "ix": ix.astype(int),
            "iy": iy.astype(int),
            "iz": iz.astype(int),
            # ── densidad ─────────────────────────────────────────────────────────
            "density": density.astype(float),          # legacy alias
            "rho": density.astype(float),               # legacy alias
            "density_t_m3": density.astype(float),      # v4.0 canonical
            "density_contrast_t_m3": density_contrast.astype(float),   # v4.0
            "density_anomaly_score": density_anomaly_score.astype(float),  # v4.0
            # ── otros ────────────────────────────────────────────────────────────
            "probability": probability.astype(float),
            "relative_target_score": probability.astype(float),
            "visual_score": visual_score.astype(float),
            "grade": grade.astype(float),
            "modeled_rock_mass_tonnes": modeled_rock_mass_tonnes.astype(float),
            "density_zone_flag": density_zone_flag.astype(int),
            "density_confidence_tier": density_confidence_tier.astype(int),
            "is_active": is_active.astype(bool),
        }
    )

    return df_full


def build_anomaly_dataframe(df_full: pl.DataFrame, cutoff_density: float):
    if len(df_full) == 0:
        return df_full

    # Filtro físico de anomalías: basado en señal primaria de inversión gravimétrica.
    # - density >= cutoff_density: contraste de densidad significativo.
    # - visual_score >= 0.35: combinación normalizada de densidad × probabilidad.
    #
    # NOTA: `grade` es una heurística interpretativa (estimate_grade_from_geophysics)
    # que combina densidad, probabilidad, NIR, Fe y factor regional. NO debe decidir
    # por sí sola la pertenencia al conjunto de anomalías físicas, porque infla el
    # conteo cuando los parámetros geoquímicos satelitales (nir, fe) son altos.
    # `grade` se conserva como columna informativa en el block model y en la salida
    # de vóxeles, pero no participa en la selección de anomalías.
    df_anomaly = (
        df_full
        .filter(
            (pl.col("density") >= cutoff_density)
            | (pl.col("visual_score") >= 0.35)
        )
        .sort("visual_score", descending=True)
    )

    return df_anomaly
