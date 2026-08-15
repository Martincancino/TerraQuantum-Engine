"""
PREPROCESAMIENTO GRAVIMÉTRICO — proyección y separación regional-residual.
================================================================================
Cierra el "gap industrial #2" documentado en la auditoría: los pasos que el
motor de inversión (``gravimetry.py``) NO realizaba y que hasta ahora se hacían
a mano en los scripts de auditoría. Llevarlos al motor los hace reproducibles,
testeables y consistentes entre runs.

Pipeline típico (datos de campo crudos → entrada de la inversión):

    from exploration.preprocessing import (
        project_geographic_to_local, remove_regional_trend, residual_mgal_to_si,
    )

    x, z, meta = project_geographic_to_local(lon, lat)        # grados → metros
    residual, regional, coef = remove_regional_trend(x, z, bouguer_mgal, order=2)
    g_si = residual_mgal_to_si(residual)                      # mGal → m/s²

Convenciones (idénticas al motor, ver gravimetry.py):
    - x, z : ejes horizontales en metros (origen en la esquina SW de los datos).
    - y    : profundidad, positiva hacia abajo (la fija la grilla, no estos pasos).
    - gravedad: el motor trabaja en SI (m/s²); 1 mGal = 1e-5 m/s².

Relación con el resto del backend:
    - La PROYECCIÓN de producción vive en ``services/coordinate_transform_service.py``
      (reproyección UTM vía pyproj con fallback equirectangular, detección de CRS y
      shift al origen SW). ``project_geographic_to_local`` de este módulo es una
      versión ligera (solo numpy) para los scripts de auditoría standalone; NO debe
      reemplazar al servicio en la ruta de producción.
    - La SEPARACIÓN REGIONAL-RESIDUAL (``remove_regional_trend``) es el paso que el
      backend de producción NO tenía: se integra vía ``services.gravity_preprocessing_service``.

Notas físicas:
    - La proyección es equirectangular (plana local). Es exacta a ~0.1% para
      ventanas de pocos cientos de km; para escalas continentales conviene UTM.
    - La separación regional-residual ajusta y RESTA una tendencia polinómica de
      bajo orden (campo regional profundo/lejano) para aislar la anomalía local
      del cuerpo objetivo. El residual tiene media ~0 por construcción y se
      invierte DIRECTAMENTE (no se le aplica ningún shift DC: hacerlo introduce
      masa difusa profunda espuria — bug corregido en la auditoría de Bushveld).
"""
from __future__ import annotations

import logging
from typing import Optional

import numpy as np

logger = logging.getLogger(__name__)

# Constantes geodésicas (WGS-84, longitud de 1° a la latitud media)
_M_PER_DEG_LAT = 110540.0          # metros por grado de latitud (≈ constante)
_M_PER_DEG_LON_EQUATOR = 111320.0  # metros por grado de longitud en el ecuador
MGAL_TO_SI = 1.0e-5                # 1 mGal = 1e-5 m/s²


def project_geographic_to_local(
    lon,
    lat,
    lon0: Optional[float] = None,
    lat0: Optional[float] = None,
):
    """
    Proyección equirectangular de coordenadas geográficas a metros locales.

    Parameters
    ----------
    lon, lat : array-like
        Longitud y latitud en GRADOS decimales.
    lon0, lat0 : float, opcional
        Origen de longitud/latitud. Por defecto se usa ``lon.min()`` / ``lat.min()``
        (esquina SW de los datos), de modo que x, z ≥ 0.

    Returns
    -------
    x : ndarray
        Coordenada E-W en metros (positiva hacia el este desde ``lon0``).
    z : ndarray
        Coordenada N-S en metros (positiva hacia el norte desde ``lat0``).
    meta : dict
        ``lon0``, ``lat0``, ``lat_mean_deg`` y factores de escala usados —
        suficientes para invertir la proyección o reproducirla.

    Notes
    -----
    El factor de escala en longitud usa la latitud MEDIA del dataset
    (``cos(lat_media)``), aproximación estándar para una ventana local.
    """
    lon = np.asarray(lon, dtype=np.float64)
    lat = np.asarray(lat, dtype=np.float64)
    if lon.shape != lat.shape:
        raise ValueError(f"lon y lat deben tener la misma forma: {lon.shape} vs {lat.shape}")
    if lon.size == 0:
        raise ValueError("lon/lat vacíos: no hay estaciones que proyectar.")

    if lon0 is None:
        lon0 = float(np.min(lon))
    if lat0 is None:
        lat0 = float(np.min(lat))

    lat_mean = float(np.mean(lat))
    scale_lon = _M_PER_DEG_LON_EQUATOR * np.cos(np.radians(lat_mean))

    x = (lon - lon0) * scale_lon
    z = (lat - lat0) * _M_PER_DEG_LAT

    meta = {
        "lon0": lon0,
        "lat0": lat0,
        "lat_mean_deg": lat_mean,
        "scale_lon_m_per_deg": float(scale_lon),
        "scale_lat_m_per_deg": _M_PER_DEG_LAT,
        "projection": "equirectangular_local",
    }
    logger.info(
        "[PREPROC] Proyección equirectangular: %d estaciones | "
        "x 0..%.1f km | z 0..%.1f km (lat media %.3f°)",
        lon.size, x.max() / 1000.0, z.max() / 1000.0, lat_mean,
    )
    return x, z, meta


def _polynomial_design_matrix(xs, zs, order: int) -> np.ndarray:
    """Matriz de diseño de un polinomio 2D de grado ``order`` en (xs, zs)."""
    cols = [np.ones_like(xs)]
    for i in range(1, order + 1):
        for j in range(i + 1):
            cols.append((xs ** (i - j)) * (zs ** j))
    return np.column_stack(cols)


def remove_regional_trend(x, z, g, order: int = 2):
    """
    Separación regional-residual por ajuste polinómico de bajo orden.

    Ajusta una tendencia polinómica 2D de grado ``order`` a la anomalía ``g``
    (p.ej. Bouguer) y la RESTA. La tendencia representa el campo regional
    (fuentes profundas/lejanas); el residual aísla la anomalía local del cuerpo
    objetivo y es lo que se invierte.

    Parameters
    ----------
    x, z : array-like
        Coordenadas horizontales en metros (salida de
        :func:`project_geographic_to_local`).
    g : array-like
        Anomalía observada (mGal típicamente).
    order : int
        Grado del polinomio regional (1=plano, 2=cuadrático estándar).
        Debe ser ≥ 0 y producir menos términos que estaciones.

    Returns
    -------
    residual : ndarray
        ``g - regional``. Media ≈ 0. Se invierte DIRECTAMENTE (sin shift DC).
    regional : ndarray
        Tendencia ajustada (mismo tamaño que ``g``).
    coef : ndarray
        Coeficientes del ajuste por mínimos cuadrados.

    Notes
    -----
    Para estabilidad numérica las coordenadas se normalizan a [0,1] antes de
    construir la matriz de diseño (evita potencias de números grandes).
    """
    x = np.asarray(x, dtype=np.float64)
    z = np.asarray(z, dtype=np.float64)
    g = np.asarray(g, dtype=np.float64)
    if not (x.shape == z.shape == g.shape):
        raise ValueError("x, z, g deben tener la misma forma.")
    if order < 0:
        raise ValueError(f"order debe ser ≥ 0, recibido {order}.")

    n_terms = (order + 1) * (order + 2) // 2
    if g.size <= n_terms:
        raise ValueError(
            f"Insuficientes estaciones ({g.size}) para un polinomio de grado "
            f"{order} ({n_terms} términos). Reduce el orden o amplía la ventana."
        )

    span_x = np.ptp(x)
    span_z = np.ptp(z)
    xs = (x - x.min()) / span_x if span_x > 0 else np.zeros_like(x)
    zs = (z - z.min()) / span_z if span_z > 0 else np.zeros_like(z)

    A = _polynomial_design_matrix(xs, zs, order)
    coef, *_ = np.linalg.lstsq(A, g, rcond=None)
    regional = A @ coef
    residual = g - regional

    logger.info(
        "[PREPROC] Regional poly-%d removido. Residual: min=%.2f max=%.2f std=%.2f "
        "(media=%.3f)",
        order, residual.min(), residual.max(), residual.std(), residual.mean(),
    )
    return residual, regional, coef


def residual_mgal_to_si(residual_mgal):
    """
    Convierte una anomalía residual de mGal a SI (m/s²) para la inversión.

    El motor (``solve_inversion_lsqr``) espera ``g_observed`` en m/s². El residual
    de :func:`remove_regional_trend` se pasa TAL CUAL (media-cero): no se le aplica
    ningún offset/shift — restar el mínimo introduce masa difusa profunda espuria.
    """
    return np.asarray(residual_mgal, dtype=np.float64) * MGAL_TO_SI


# Fase 6 (cierre, H-13): aquí vivía `upward_continue_gravity_fft` (151 líneas),
# continuación hacia arriba por FFT 2D. Cero llamadores de producción y cero tests
# en todo el repositorio: medido el 2026-08-14 con el cruce de referencias AST sobre
# código + tests + scripts, su única aparición era su propia definición.
#
# Es el mismo cadáver de experimento que `remove_regional_scale` (abajo) y de la misma
# familia: ambos servían al pipeline regional de Bushveld, que este proyecto midió y
# descartó (`docs/06` §9 y la conclusión H-A6/H-A7: el caso regional es depth-ambiguo
# e irresoluble sin geología). Su docstring seguía enseñando ese pipeline como «uso
# típico», así que documentaba una ruta que el producto no toma.
#
# Por qué BORRAR y no congelar (regla de la Fase 6): un operador FFT correcto pero sin
# un solo test, sentado en el módulo de preprocesamiento, es una invitación a cablear
# física no validada al camino crítico — exactamente el pecado que la Fase 1 rechazó
# con el modo `amplitude`. Si vuelve a hacer falta, `git log` lo tiene íntegro.

# Fase 6 (H-13): aquí vivía `remove_regional_scale` (169 líneas), con cero llamadores
# en todo el repositorio desde que se escribió.
#
# NO confundir con `remove_regional_trend` (más arriba), que SÍ es producción: la usa
# `gravity_preprocessing_service` cuando el usuario pide `remove_regional=true`. Lo que
# se borró es el experimento de ESCALADO regional, que además quedó refutado como cura
# del hundimiento de Laguna del Maule.

