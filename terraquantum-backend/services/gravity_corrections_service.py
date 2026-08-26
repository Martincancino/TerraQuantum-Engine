"""
Servicio de correcciones de gravedad — Fase 1 del Plan Industrial Tier 1.
=========================================================================
Implementa las correcciones estándar para reducir datos de campo a anomalía
de Bouguer completa, lista para inversión:

    g_raw  →  FAA  →  simple_BA  →  complete_BA
              FAC      FAC + BC        FAC + BC + TC

Fórmulas de referencia:
    - GRS80: Moritz (1980 — IUGG)
    - FAC:   Heiskanen & Moritz (1967) fórmula 3-57
    - BC:    Hinze et al. (2005), Geophysics (coeficiente CODATA 2018)
    - TC:    Hammer (1939) / Kane (1962) — columna vertical (línea de masa)
"""
from __future__ import annotations

import logging
from typing import List, Optional, Tuple

import numpy as np

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Constantes físicas (CODATA 2018 / GRS80)
# ---------------------------------------------------------------------------
_G_NEWTON = 6.6743e-11        # m³ kg⁻¹ s⁻²   (CODATA 2018)
_GRS80_GAMMA_E = 9.7803267715  # m/s²  gravedad normal en el ecuador
_GRS80_K = 0.001931851353      # constante de Somigliana
_GRS80_E2 = 0.0066943800229    # primera excentricidad² de GRS80
_BOUGUER_COEF = 0.04193        # mGal / (m · g/cm³)  — usa G_CODATA2018
_FAC_A = 0.3087691             # mGal/m  (coeficiente de primer orden, lat-dep)
_FAC_B = 0.0004398             # mGal/m  (término de sin²phi)
_FAC_H2 = 7.2125e-8            # mGal/m² (segundo orden)


# ---------------------------------------------------------------------------
# 1. Corrección de latitud — Gravedad normal GRS80
# ---------------------------------------------------------------------------

def compute_normal_gravity_grs80(latitudes_deg: np.ndarray) -> np.ndarray:
    """
    Gravedad teórica según GRS80 (Moritz 1980 — IUGG), fórmula de Somigliana.

    Returns: gamma [m/s²] — mismas unidades que g_obs si ya está en m/s².
    Para convertir a mGal: multiplicar por 1e5.
    """
    phi = np.radians(np.asarray(latitudes_deg, dtype=np.float64))
    sin2 = np.sin(phi) ** 2
    gamma = _GRS80_GAMMA_E * (1.0 + _GRS80_K * sin2) / np.sqrt(1.0 - _GRS80_E2 * sin2)
    return gamma  # m/s²


def compute_normal_gravity_mgal(latitudes_deg: np.ndarray) -> np.ndarray:
    """Gravedad normal GRS80 en mGal."""
    return compute_normal_gravity_grs80(latitudes_deg) * 1e5


# ---------------------------------------------------------------------------
# 2. Corrección Free-Air (FAC)
# ---------------------------------------------------------------------------

def compute_free_air_correction(
    elevations_m: np.ndarray,
    latitudes_deg: np.ndarray,
) -> np.ndarray:
    """
    Corrección Free-Air dependiente de latitud [mGal].

    Valor positivo para h > 0: se SUMA al g_obs para llevar la medición al
    nivel de referencia del elipsoide.

    Referencia: Heiskanen & Moritz (1967), fórmula 3-57.
    """
    phi = np.radians(np.asarray(latitudes_deg, dtype=np.float64))
    h = np.asarray(elevations_m, dtype=np.float64)
    fac_coef = _FAC_A - _FAC_B * np.sin(phi) ** 2  # mGal/m
    fac = fac_coef * h - _FAC_H2 * h ** 2           # mGal
    return fac


# Fase 6 (cierre, H-13): aquí vivía `compute_free_air_correction_simple` — la FAC de
# coeficiente fijo 0.3086 mGal/m. Cero llamadores: el pipeline usa siempre la versión
# dependiente de latitud de arriba, que es estrictamente mejor y cuesta lo mismo.
# Mantener las dos era ofrecer una elección que nadie debe tomar: la única diferencia
# posible es un resultado peor.


# ---------------------------------------------------------------------------
# 3. Corrección Bouguer de placa infinita (BC)
# ---------------------------------------------------------------------------

def compute_bouguer_correction(
    elevations_m: np.ndarray,
    reduction_density_gcc: float = 2.67,
) -> np.ndarray:
    """
    Corrección Bouguer de placa infinita [mGal].

    Valor positivo: se RESTA del FAA para obtener la anomalía de Bouguer simple.
    (El plato de masa adicional aumenta la atracción → se sustrae.)

    Coeficiente 0.04193: usa G = 6.6743e-11 (CODATA 2018).
    Referencia: Hinze et al. (2005), Geophysics — NAGD standardization.
    """
    h = np.asarray(elevations_m, dtype=np.float64)
    bc = _BOUGUER_COEF * float(reduction_density_gcc) * h  # mGal
    return bc


# ---------------------------------------------------------------------------
# 4. Corrección de Terreno (TC) — columna vertical (componente vertical)
# ---------------------------------------------------------------------------

def compute_terrain_correction_column(
    station_x_m: np.ndarray,
    station_z_m: np.ndarray,
    station_elev_m: np.ndarray,
    dem_x_grid: np.ndarray,
    dem_z_grid: np.ndarray,
    dem_elev_grid: np.ndarray,
    dem_cell_size_m: float,
    reduction_density_gcc: float = 2.67,
    max_radius_m: float = 22000.0,
) -> np.ndarray:
    """
    Corrección de terreno por COLUMNA VERTICAL de masa [mGal].

    Cada celda del DEM se trata como una columna vertical de sección
    ``dem_cell_size_m²`` que va desde la cota de la estación hasta la cota del
    terreno, y se suma la COMPONENTE VERTICAL de su atracción — que es lo que
    mide un gravímetro. Integrando z/(r²+z²)^{3/2} entre 0 y Δh:

        TC = Σ G·ρ·A·(1/r − 1/√(r²+Δh²))                   [forma cerrada]
           = Σ G·ρ·A·Δh² / (r·s·(r+s)),  s = √(r²+Δh²)      [forma estable]
           ≈ Σ G·ρ·A·Δh²/(2r³)                              [límite campo lejano]

    con ``r`` la distancia HORIZONTAL estación–celda y ``Δh`` el desnivel.
    Las tres primeras líneas son la misma álgebra; se implementa la SEGUNDA
    porque la primera pierde dígitos por cancelación cuando Δh ≪ r (medido:
    8·10⁻⁶ de error relativo a r=22 km con Δh=0,1 m) y porque el límite de campo
    lejano diverge como 1/r³ en terreno escarpado cercano (medido: 202× el
    prisma de Nagy para Δh=1000 m a r=50 m, frente a 0,96× de la forma cerrada).

    HISTORIA — esto es lo que arregla la Fase 17 (defecto ACAD-0). Hasta
    2026-08-25 la función sumaba ``G·ρ·A·|Δh|/r²``: el MÓDULO de la atracción de
    una masa puntual, sin proyectar sobre la vertical. Le faltaba el factor
    Δh/(2r), así que sobrestimaba por ``2r/|Δh|`` — un factor que CRECE con la
    distancia, con radio de integración por defecto de 22 km. Medido: 200× para
    una celda a 1 km con 10 m de desnivel, 66× a 1 km con 30 m, y 14,8× en el
    total de un cono de 500 m, sobre una señal de exploración de 0,1–10 mGal.

    APROXIMACIONES QUE SIGUEN VIVAS (no son bugs, son el modelo):
      - La sección de la celda se colapsa a un punto en el horizontal. El error
        contra el prisma exacto de Nagy decae como ≈0,375·(celda/r)²: medido
        9,4·10⁻⁴ a r=20 celdas y 7,9·10⁻² a r=2 celdas. Siempre SUBESTIMA
        (0,71–0,99 del prisma), nunca diverge.
      - La celda que contiene la estación (r=0) queda excluida por la máscara.

    TC es siempre ≥ 0, ahora por CONSTRUCCIÓN y no por recorte: el numerador es
    Δh² y el denominador es positivo para todo r>0. Físicamente: el terreno
    alrededor de una estación siempre reduce la gravedad medida, ya sea por masa
    por encima o por el "hueco" relativo debajo del plano de Bouguer. La fórmula
    es simétrica en Δh — colina y valle del mismo desnivel aportan lo mismo.

    Args:
        station_x_m, station_z_m: coordenadas locales de las estaciones [m]
        station_elev_m: elevación de cada estación [m AMSL]
        dem_x_grid (1-D): vector de coordenadas X del DEM [m]
        dem_z_grid (1-D): vector de coordenadas Z del DEM [m]
        dem_elev_grid (2-D): matriz de elevaciones DEM [m AMSL], shape (nz, nx)
        dem_cell_size_m: tamaño de celda del DEM [m]
        reduction_density_gcc: densidad de reducción [g/cm³]
        max_radius_m: radio máximo de integración [m]

    Returns: TC [mGal] — siempre >= 0.
    """
    rho_kg_m3 = float(reduction_density_gcc) * 1000.0
    cell_area = dem_cell_size_m ** 2  # m²

    n_stations = len(station_x_m)
    tc = np.zeros(n_stations)

    dem_x = np.asarray(dem_x_grid, dtype=np.float64)
    dem_z = np.asarray(dem_z_grid, dtype=np.float64)
    dem_elev = np.asarray(dem_elev_grid, dtype=np.float64)
    dem_xx, dem_zz = np.meshgrid(dem_x, dem_z)  # (nz, nx)
    dem_flat_x = dem_xx.ravel()
    dem_flat_z = dem_zz.ravel()
    dem_flat_elev = dem_elev.ravel()

    for i in range(n_stations):
        sx, sz, se = float(station_x_m[i]), float(station_z_m[i]), float(station_elev_m[i])
        dx = dem_flat_x - sx
        dz = dem_flat_z - sz
        r = np.sqrt(dx ** 2 + dz ** 2)

        mask = (r > 0.0) & (r <= max_radius_m)
        if not np.any(mask):
            continue

        r_m = r[mask]
        dh = dem_flat_elev[mask] - se  # positive = terrain above station

        # Componente VERTICAL de la columna de masa, forma cerrada estable.
        # Equivale a G·ρ·A·(1/r − 1/√(r²+Δh²)) sin la cancelación catastrófica
        # que esa resta sufre cuando Δh ≪ r.
        s_m = np.sqrt(r_m ** 2 + dh ** 2)
        tc_contrib = (
            _G_NEWTON * rho_kg_m3 * cell_area * dh ** 2
            / (r_m * s_m * (r_m + s_m))
        )
        # Convert m/s² → mGal
        tc[i] = np.sum(tc_contrib) * 1e5

    # Sin np.maximum(tc, 0.0): la no-negatividad es ESTRUCTURAL (numerador Δh²,
    # denominador > 0 para todo r > 0). Un recorte aquí sería un guard inerte
    # que aparentaría defender algo que la fórmula ya garantiza.
    return tc


# Alias deprecados. Dos nombres históricos, los dos mentían sobre la fórmula:
#   - ``_prism``     prometía el prisma exacto de Nagy y nunca lo fue (Fase 0).
#   - ``_pointmass`` describía G·ρ·A·|Δh|/r², el MÓDULO de una masa puntual, que
#     era justamente el defecto ACAD-0 que corrige la Fase 17.
# La implementación es una COLUMNA vertical, y el nombre ahora lo dice.
# Conservados para no romper callers; preferir ``compute_terrain_correction_column``.
compute_terrain_correction_pointmass = compute_terrain_correction_column
compute_terrain_correction_prism = compute_terrain_correction_column


# ---------------------------------------------------------------------------
# 4b. F2B — Pre-reducciones de CAMPO (marea Longman + deriva instrumental)
# ---------------------------------------------------------------------------

def apply_field_prereductions(
    lats_deg: np.ndarray,
    lons_deg: np.ndarray,
    elevs_m: np.ndarray,
    g_obs_mgal: np.ndarray,
    station_ids: "list[str]",
    time_strings: "list[str] | None",
    apply_tide: bool = False,
    apply_drift: bool = False,
    drift_method: str = "linear",
    base_station_id: "str | None" = None,
) -> "Tuple[np.ndarray, dict]":
    """F2B — Pre-reducciones de CAMPO sobre lecturas crudas: marea y deriva.

    Orden estándar de gabinete: MAREA primero (Longman 1959, astronomía pura),
    DERIVA después (los cierres de base se evalúan sobre lecturas ya libres de
    marea). Ambas son previas a la cadena GRS80→FAC→Bouguer→TC existente y
    solo tienen sentido sobre g_raw (el llamador lo valida).

    Nunca adivina: sin columna de tiempo parseable → ValueError con formatos
    aceptados; deriva sin base_station_id → ValueError que PREGUNTA e incluye
    la candidata detectada (id repetido con más ocupaciones), patrón
    needs_context.
    """
    from services.drift_correction_service import (
        DriftInputError,
        correct_drift,
        suggest_base_station,
    )
    from services.earth_tide_service import (
        parse_survey_timestamps,
        solve_longman_tide,
    )

    g = np.asarray(g_obs_mgal, dtype=np.float64).copy()
    meta: dict = {"corrections_applied": [], "warnings": []}
    if not (apply_tide or apply_drift):
        return g, meta

    if not time_strings or all(not str(t).strip() for t in time_strings):
        raise ValueError(
            "La corrección de marea/deriva requiere la hora de cada lectura: "
            "agregue la columna de tiempo (time_utc) por estación. Formatos "
            "aceptados: 'YYYY-MM-DD HH:MM[:SS]' o ISO-8601 (UTC)."
        )
    times = parse_survey_timestamps([str(t) for t in time_strings])
    if times is None:
        raise ValueError(
            "La columna de tiempo tiene valores ilegibles: TODOS los timestamps "
            "deben parsear (una corrección de marea/deriva a medias corrompería "
            "en silencio). Formatos: 'YYYY-MM-DD HH:MM[:SS]' o ISO-8601 (UTC)."
        )

    if apply_tide:
        tide = np.array([
            solve_longman_tide(
                float(lats_deg[i]), float(lons_deg[i]),
                float(elevs_m[i]) if np.isfinite(elevs_m[i]) else 0.0,
                times[i],
            )[2]
            for i in range(len(g))
        ])
        g = g - tide   # g_corregida = g_leída − aceleración de marea
        meta["corrections_applied"].append("earth_tide_longman1959")
        meta["tide_min_mgal"] = float(tide.min())
        meta["tide_max_mgal"] = float(tide.max())

    if apply_drift:
        ids_norm = [str(s).strip().casefold() for s in station_ids]
        if not base_station_id:
            cand = suggest_base_station([str(s).strip() for s in station_ids])
            hint = (
                f" Candidata detectada: '{cand[0]}' ({cand[1]} ocupaciones)."
                if cand else
                " Ningún station_id se repite: sin re-ocupaciones no hay "
                "cierres que midan la deriva."
            )
            raise ValueError(
                "La corrección de deriva necesita saber cuál es la estación "
                "BASE (base_station_id) cuyas re-ocupaciones cierran el loop." + hint
            )
        is_base = np.array(
            [sid == str(base_station_id).strip().casefold() for sid in ids_norm]
        )
        if int(is_base.sum()) == 0:
            raise ValueError(
                f"base_station_id='{base_station_id}' no aparece en las "
                "estaciones: verifique el identificador de la base."
            )
        # correct_drift exige tiempos crecientes: ordenar, corregir, restaurar.
        order = np.argsort([t.timestamp() for t in times], kind="stable")
        inv = np.empty_like(order)
        inv[order] = np.arange(len(order))
        try:
            res = correct_drift(
                [times[i] for i in order], g[order], is_base[order],
                method=drift_method,
            )
        except DriftInputError as exc:
            raise ValueError(str(exc)) from exc
        g = res.corrected_mgal[inv]
        meta["corrections_applied"].append(f"instrument_drift_{res.method}")
        meta["drift_rate_mgal_per_day"] = res.drift_rate_mgal_per_day
        meta["drift_closure_mgal"] = res.closure_mgal
        meta["drift_n_base"] = res.n_base_occupations
        meta["warnings"].extend(res.warnings)

    return g, meta


# ---------------------------------------------------------------------------
# 5. Aplicar correcciones completas
# ---------------------------------------------------------------------------

def apply_all_corrections(
    lats_deg: np.ndarray,
    lons_deg: np.ndarray,
    elevs_m: np.ndarray,
    g_obs_mgal: np.ndarray,
    gravity_type_in: str,
    reduction_density_gcc: float = 2.67,
    apply_lat: bool = True,
    apply_fac: bool = True,
    apply_bouguer: bool = True,
    apply_terrain: bool = False,
    tc_values_mgal: Optional[np.ndarray] = None,
) -> Tuple[np.ndarray, dict]:
    """
    Reduce datos de campo a anomalía de Bouguer (simple o completa).

    Pipeline:
        g_raw  →  g_obs - gamma  →  FAA = above + FAC  →  BA = FAA - BC  →  CBA = BA + TC

    Para datos que ya son free_air_anomaly o bouguer_anomaly, salta las
    correcciones que ya se aplicaron (controlado por gravity_type_in).

    Returns:
        g_reduced [mGal] — anomalía lista para inversión
        meta dict — componentes individuales para el reporte/QAQC
    """
    lats = np.asarray(lats_deg, dtype=np.float64)
    elevs = np.asarray(elevs_m, dtype=np.float64)
    g = np.asarray(g_obs_mgal, dtype=np.float64)

    if np.any(np.isnan(elevs)) and (apply_fac or apply_bouguer or apply_terrain):
        raise ValueError(
            "Se requieren elevaciones para calcular FAC/BC/TC. "
            "Proporcione la columna de elevación en el CSV."
        )

    meta: dict = {
        "gravity_type_in": gravity_type_in,
        "n_stations": int(len(g)),
        "corrections_applied": [],
    }

    gamma_mgal = fac_mgal = bc_mgal = tc_arr = None
    g_reduced = g.copy()

    already_lat = gravity_type_in in ("free_air_anomaly", "bouguer_anomaly", "complete_bouguer_anomaly")
    already_fac = gravity_type_in in ("free_air_anomaly", "bouguer_anomaly", "complete_bouguer_anomaly")
    already_bc = gravity_type_in in ("bouguer_anomaly", "complete_bouguer_anomaly")
    already_tc = gravity_type_in == "complete_bouguer_anomaly"

    # Latitude (normal gravity)
    if apply_lat and not already_lat:
        gamma_mgal = compute_normal_gravity_mgal(lats)
        g_reduced = g_reduced - gamma_mgal
        meta["corrections_applied"].append("latitude_grs80")
        meta["gamma_min_mgal"] = float(gamma_mgal.min())
        meta["gamma_max_mgal"] = float(gamma_mgal.max())

    # Free-Air
    if apply_fac and not already_fac:
        fac_mgal = compute_free_air_correction(elevs, lats)
        g_reduced = g_reduced + fac_mgal
        meta["corrections_applied"].append("free_air")
        meta["fac_min_mgal"] = float(fac_mgal.min())
        meta["fac_max_mgal"] = float(fac_mgal.max())

    # Bouguer
    if apply_bouguer and not already_bc:
        bc_mgal = compute_bouguer_correction(elevs, reduction_density_gcc)
        g_reduced = g_reduced - bc_mgal
        meta["corrections_applied"].append("bouguer")
        meta["bc_min_mgal"] = float(bc_mgal.min())
        meta["bc_max_mgal"] = float(bc_mgal.max())

    # Terrain
    if apply_terrain and not already_tc:
        if tc_values_mgal is None:
            logger.warning(
                "[CORR] apply_terrain=True pero tc_values_mgal no provisto; "
                "corrección de terreno omitida."
            )
        else:
            tc_arr = np.asarray(tc_values_mgal, dtype=np.float64)
            if np.any(tc_arr < -1e-9):
                raise ValueError("tc_values_mgal contiene valores negativos (matemáticamente imposible).")
            g_reduced = g_reduced + tc_arr
            meta["corrections_applied"].append("terrain")
            meta["tc_min_mgal"] = float(tc_arr.min())
            meta["tc_max_mgal"] = float(tc_arr.max())

    meta["g_reduced_min_mgal"] = float(g_reduced.min())
    meta["g_reduced_max_mgal"] = float(g_reduced.max())
    meta["g_reduced_mean_mgal"] = float(g_reduced.mean())
    meta["g_reduced_std_mgal"] = float(g_reduced.std())

    # Output type
    applied = set(meta["corrections_applied"])
    if "terrain" in applied:
        meta["output_gravity_type"] = "complete_bouguer_anomaly"
    elif "bouguer" in applied or already_bc:
        meta["output_gravity_type"] = "bouguer_anomaly"
    else:
        meta["output_gravity_type"] = "free_air_anomaly"

    logger.info(
        "[CORR] %d estaciones — correcciones: %s → tipo_salida=%s "
        "g_mean=%.4g g_std=%.4g mGal",
        meta["n_stations"],
        meta["corrections_applied"],
        meta["output_gravity_type"],
        meta["g_reduced_mean_mgal"],
        meta["g_reduced_std_mgal"],
    )
    return g_reduced, meta


# ---------------------------------------------------------------------------
# 6. Test de Nettleton
# ---------------------------------------------------------------------------

def nettleton_analysis(
    g_obs_mgal: np.ndarray,
    elevs_m: np.ndarray,
    lats_deg: np.ndarray,
    densities_to_test: Optional[np.ndarray] = None,
) -> dict:
    """
    Análisis de Nettleton: densidad de reducción que minimiza correlación
    |r(BA, elevación)|.

    Returns dict con: {densities, correlations, best_density_gcc, best_r}
    """
    if densities_to_test is None:
        densities_to_test = np.arange(1.8, 3.5, 0.05)

    g = np.asarray(g_obs_mgal, dtype=np.float64)
    h = np.asarray(elevs_m, dtype=np.float64)
    lats = np.asarray(lats_deg, dtype=np.float64)

    # Siempre aplicar latitud + FAC (independientes de la densidad)
    gamma = compute_normal_gravity_mgal(lats)
    fac = compute_free_air_correction(h, lats)
    faa = g - gamma + fac  # Free-Air anomaly

    correlations = []
    for rho in densities_to_test:
        bc = compute_bouguer_correction(h, float(rho))
        ba = faa - bc
        r = float(np.corrcoef(ba, h)[0, 1]) if h.std() > 0 and ba.std() > 0 else 0.0
        correlations.append(r)

    correlations = np.array(correlations)
    abs_r = np.abs(correlations)
    best_idx = int(np.argmin(abs_r))

    return {
        "densities_gcc": densities_to_test.tolist(),
        "correlations": correlations.tolist(),
        "best_density_gcc": float(densities_to_test[best_idx]),
        "best_r": float(correlations[best_idx]),
        "warning": (
            f"r={correlations[best_idx]:.3f} en densidad óptima {densities_to_test[best_idx]:.2f} g/cm³. "
            "Considere otra densidad si |r| > 0.3."
            if abs_r[best_idx] > 0.3 else None
        ),
    }
