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


def upward_continue_gravity_fft(
    x_pts,
    z_pts,
    g_data,
    height_m: float = 3000.0,
    grid_step: Optional[float] = None,
):
    """
    Continuación hacia arriba (upward continuation) vía FFT 2D.

    Traslada el campo gravimétrico ``g_data`` a una altura virtual ``height_m``
    sobre el plano de observación. En el dominio de ondas el operador es:

        G_up(kx, kz) = G(kx, kz) · exp(−|k| · h)

    donde |k| = 2π · sqrt(fx² + fz²) es el número de onda angular [rad/m] y
    h = ``height_m``.  La exponencial es de decaimiento puro (≤ 1 para todo k),
    por lo que la operación es estable y actúa como paso-bajo espacial: atenúa
    anomalías de corta longitud de onda (fuentes superficiales/poco profundas) y
    preserva el campo regional de larga longitud de onda.

    Uso típico en el pipeline Bushveld::

        residual, _, _ = remove_regional_trend(x, z, g_raw, order=2)
        residual_uc    = upward_continue_gravity_fft(x, z, residual, height_m=3000.0)
        g_si           = residual_mgal_to_si(residual_uc)

    Parameters
    ----------
    x_pts, z_pts : array-like, shape (n,)
        Coordenadas horizontales de los sensores [metros].
    g_data : array-like, shape (n,)
        Anomalía gravimétrica a continuar [cualquier unidad lineal, p.ej. mGal].
    height_m : float
        Altura de continuación en metros. Valores típicos: 2 000–5 000 m.
        Mayor altura → mayor suavizado / remoción de señal superficial.
    grid_step : float, opcional
        Tamaño de celda de la grilla FFT intermedia [metros]. Por defecto se usa
        el percentil-10 de las separaciones entre estaciones vecinas (proxy de
        paso de muestreo), limitado a ≥ 500 m para evitar grillas excesivamente
        densas.

    Returns
    -------
    g_continued : ndarray, shape (n,)
        Campo upward-continued en las posiciones originales ``(x_pts, z_pts)``.
        Comparte unidades con ``g_data``.

    Notes
    -----
    *Interpolación bidireccional* — los datos dispersos se llevan a una grilla
    regular por *cubic griddata* (con *fill_value* = media de los datos para
    extrapolar fuera de la envolvente convexa); el resultado del filtro se
    devuelve a los sensores originales por interpolación bilineal.

    *Zero-padding* — la grilla se rellena hasta la próxima potencia de 2 en cada
    dimensión para maximizar la velocidad de la FFT y reducir el aliasing
    circular (wrapping).
    """
    from scipy.fft import fft2, ifft2, fftfreq
    from scipy.interpolate import griddata

    x_pts = np.asarray(x_pts, dtype=np.float64)
    z_pts = np.asarray(z_pts, dtype=np.float64)
    g_data = np.asarray(g_data, dtype=np.float64)

    if x_pts.shape != z_pts.shape or x_pts.shape != g_data.shape:
        raise ValueError("x_pts, z_pts y g_data deben tener la misma forma.")
    if x_pts.size < 4:
        raise ValueError("Se necesitan al menos 4 estaciones para upward continuation.")
    if height_m <= 0:
        raise ValueError("height_m debe ser positivo.")

    # ── 1. Determinar paso de grilla ─────────────────────────────────────────
    if grid_step is None:
        # Estimación robusta: percentil-10 de distancias a vecino más cercano
        from scipy.spatial import cKDTree
        tree = cKDTree(np.column_stack([x_pts, z_pts]))
        dists, _ = tree.query(np.column_stack([x_pts, z_pts]), k=2)
        nn_dists = dists[:, 1]  # distancia al vecino más cercano
        grid_step = float(max(np.percentile(nn_dists, 10), 500.0))

    # ── 2. Grilla regular dentro del convex hull de los datos ────────────────
    x_min, x_max = x_pts.min(), x_pts.max()
    z_min, z_max = z_pts.min(), z_pts.max()
    x_grid = np.arange(x_min, x_max + grid_step, grid_step)
    z_grid = np.arange(z_min, z_max + grid_step, grid_step)
    Xg, Zg = np.meshgrid(x_grid, z_grid)

    g_mean = float(np.nanmean(g_data))
    g_grid = griddata(
        (x_pts, z_pts), g_data, (Xg, Zg),
        method="cubic", fill_value=g_mean,
    )
    g_grid = np.nan_to_num(g_grid, nan=g_mean)

    # ── 3. Zero-pad a próxima potencia de 2 ─────────────────────────────────
    ny0, nx0 = g_grid.shape

    def _next_pow2(n):
        p = 1
        while p < n:
            p <<= 1
        return p

    ny_pad = _next_pow2(2 * ny0)
    nx_pad = _next_pow2(2 * nx0)
    g_padded = np.pad(g_grid, ((0, ny_pad - ny0), (0, nx_pad - nx0)), mode="edge")

    # ── 4. FFT 2D ────────────────────────────────────────────────────────────
    G_fft = fft2(g_padded)

    # Número de onda angular [rad/m]: k = 2π · f  (fftfreq devuelve ciclos/m)
    kx = 2.0 * np.pi * fftfreq(nx_pad, d=grid_step)
    kz = 2.0 * np.pi * fftfreq(ny_pad, d=grid_step)
    Kx, Kz = np.meshgrid(kx, kz)
    K = np.sqrt(Kx ** 2 + Kz ** 2)  # |k| [rad/m]

    # ── 5. Filtro upward continuation ────────────────────────────────────────
    # exp(-|k| · h): k=0 → factor=1 (DC intacto), k↑ → atenuación creciente
    filter_uc = np.exp(-K * height_m)
    G_uc = G_fft * filter_uc

    # ── 6. IFFT → recortar padding ───────────────────────────────────────────
    g_uc_padded = np.real(ifft2(G_uc))
    g_uc_grid = g_uc_padded[:ny0, :nx0]

    # ── 7. Interpolar de vuelta a las posiciones originales ──────────────────
    g_continued = griddata(
        (Xg.ravel(), Zg.ravel()), g_uc_grid.ravel(),
        (x_pts, z_pts), method="linear",
    )
    # Fallback nearest para puntos fuera del bounding box de la grilla
    mask_nan = ~np.isfinite(g_continued)
    if mask_nan.any():
        g_fallback = griddata(
            (Xg.ravel(), Zg.ravel()), g_uc_grid.ravel(),
            (x_pts[mask_nan], z_pts[mask_nan]), method="nearest",
        )
        g_continued[mask_nan] = g_fallback

    logger.info(
        "[PREPROC] Upward continuation h=%.0f m | grid_step=%.0f m | "
        "grilla %dx%d → pad %dx%d | "
        "residual antes: media=%.3f std=%.3f | "
        "residual después: media=%.3f std=%.3f",
        height_m, grid_step, nx0, ny0, nx_pad, ny_pad,
        float(np.mean(g_data)), float(np.std(g_data)),
        float(np.mean(g_continued)), float(np.std(g_continued)),
    )
    return g_continued


def remove_regional_scale(
    x_pts,
    z_pts,
    g_data,
    height_m: float = 5000.0,
    grid_step: Optional[float] = None,
    use_highpass: bool = True,
) -> tuple:
    """
    Remueve el campo regional a escala REGIONAL (no local) mediante upward continuation.

    Diseñada para Bushveld real (350 km dominio, 441 sensores).
    Antes de hacer inversión en una ventana de 100 km, primero hay que remover
    el regional verdadero de toda la escala (350 km), no solo un polinomio local.

    Procedimiento:
        1. Interpola datos dispersos a grilla regular (grid_step ≈ spacing de sensores)
        2. Aplica FFT upward continuation a h=5-10 km (escala regional)
        3. Extrae residual = datos_originales - upward_continued
        4. Re-interpola a posiciones originales de los sensores

    Con esto:
        - El residual es más puro (anomalía local verdadera, no contaminada por borde)
        - Inversión en ventana de 100 km da depth realista (6-9 km, no 2 km alias)
        - Efecto de borde de ventana se reduce

    Parameters
    ----------
    x_pts, z_pts : array-like, shape (n,)
        Coordenadas horizontales de sensores en metros (escala completa 350 km).
    g_data : array-like, shape (n,)
        Datos gravimétricos crudos en cualquier unidad [mGal, SI, etc].
    height_m : float
        Altura de continuación hacia arriba para aislar regional [metros].
        Valores típicos: 5000–10000 m (Li & Oldenburg 1998 para regional).
        Mayor altura → más suavizado / mayor escala regional removida.
    grid_step : float, opcional
        Paso de la grilla FFT. Por defecto = percentil-10 de nearest-neighbor dists.

    Returns
    -------
    g_residual : ndarray, shape (n,)
        Anomalía residual (local) = g_data - g_regional.
        Media ≈ 0.0 (por construcción de upward continuation).
    g_regional : ndarray, shape (n,)
        Campo regional extendido (lo que se removió).
    grid_info : dict
        Información de diagnóstico (grid_step, grilla size, etc).

    Example
    -------
    >>> g_residual, g_regional, info = remove_regional_scale(
    ...     x, z, g_raw, height_m=5000
    ... )
    >>> # Ahora ventanear g_residual a 100 km e invertir da depth ≈ 6-9 km
    """
    from scipy.interpolate import griddata

    x_pts = np.asarray(x_pts, dtype=np.float64)
    z_pts = np.asarray(z_pts, dtype=np.float64)
    g_data = np.asarray(g_data, dtype=np.float64)

    if x_pts.shape != z_pts.shape or x_pts.shape != g_data.shape:
        raise ValueError("x_pts, z_pts y g_data deben tener la misma forma.")
    if x_pts.size < 4:
        raise ValueError("Se necesitan al menos 4 sensores para separación regional-residual.")
    if height_m <= 0:
        raise ValueError("height_m debe ser positivo.")

    # 1. Determinar paso de grilla
    if grid_step is None:
        from scipy.spatial import cKDTree
        tree = cKDTree(np.column_stack([x_pts, z_pts]))
        dists, _ = tree.query(np.column_stack([x_pts, z_pts]), k=2)
        nn_dists = dists[:, 1]
        grid_step = float(max(np.percentile(nn_dists, 10), 500.0))

    # 2. Crear grilla regular en dominio completo
    x_min, x_max = x_pts.min(), x_pts.max()
    z_min, z_max = z_pts.min(), z_pts.max()
    x_grid = np.arange(x_min, x_max + grid_step, grid_step)
    z_grid = np.arange(z_min, z_max + grid_step, grid_step)
    Xg, Zg = np.meshgrid(x_grid, z_grid)

    # 3. Interpolar datos a grilla
    g_mean = float(np.nanmean(g_data))
    g_grid = griddata(
        (x_pts, z_pts), g_data, (Xg, Zg),
        method="cubic", fill_value=g_mean,
    )
    g_grid = np.nan_to_num(g_grid, nan=g_mean)

    # 4. Aplicar upward continuation en la grilla completa
    # Nota: upward_continue_gravity_fft espera arrays 1D de igual forma
    # Pasar los puntos de la grilla como 1D
    x_grid_flat = Xg.ravel()  # flatten grid X
    z_grid_flat = Zg.ravel()  # flatten grid Z
    g_grid_flat = g_grid.ravel()  # flatten grid data
    g_upward_flat = upward_continue_gravity_fft(
        x_grid_flat, z_grid_flat, g_grid_flat,
        height_m=height_m, grid_step=None  # grid_step=None porque ya está en grilla regular
    )
    g_upward_grid = g_upward_flat.reshape(g_grid.shape)

    # 5. Residual local = g_grid - g_upward (filtro pasa-alto implícito)
    # IMPORTANTE: upward continuation preserva DC (k=0 → exp(0)=1)
    # Por eso g_residual = g - g_up es un filtro pasa-alto, no sustracción simple
    g_residual_grid = g_grid - g_upward_grid

    # 5B. Si use_highpass=True, aplicar filtro pasa-alto adicional explícito
    # para mejorar la remoción de wavelengths largas (mejora numéricamente)
    if use_highpass:
        # Filtro pasa-alto: g_high = g - upward_continue_again(g, h_small)
        # Usa una altura pequeña (h/2) para remover mediana wavelength
        x_grid_flat = Xg.ravel()
        z_grid_flat = Zg.ravel()
        g_res_flat = g_residual_grid.ravel()
        g_res_upward_flat = upward_continue_gravity_fft(
            x_grid_flat, z_grid_flat, g_res_flat,
            height_m=height_m / 2.0, grid_step=None
        )
        g_res_upward_grid = g_res_upward_flat.reshape(g_residual_grid.shape)
        g_residual_grid = g_residual_grid - g_res_upward_grid

    # 6. Re-interpolar a puntos originales
    g_residual = griddata(
        (Xg.ravel(), Zg.ravel()), g_residual_grid.ravel(),
        (x_pts, z_pts), method="linear",
    )
    g_regional = griddata(
        (Xg.ravel(), Zg.ravel()), g_upward_grid.ravel(),
        (x_pts, z_pts), method="linear",
    )

    # Fallback nearest para puntos fuera del bounding box
    for arr in [g_residual, g_regional]:
        mask_nan = ~np.isfinite(arr)
        if mask_nan.any():
            g_fallback = griddata(
                (Xg.ravel(), Zg.ravel()), g_grid.ravel() if arr is g_residual else g_upward_grid.ravel(),
                (x_pts[mask_nan], z_pts[mask_nan]), method="nearest",
            )
            arr[mask_nan] = g_fallback

    grid_info = {
        "height_m": height_m,
        "grid_step": grid_step,
        "grid_shape": g_grid.shape,
        "x_range_km": (x_min / 1e3, x_max / 1e3),
        "z_range_km": (z_min / 1e3, z_max / 1e3),
    }

    logger.info(
        "[PREPROC-SCALE] Regional removal (h=%.0f m) | grid_step=%.0f m | "
        "datos: %.0f-%.0f km (x), %.0f-%.0f km (z) | grilla %dx%d | "
        "g_data:  min=%.2f max=%.2f mean=%.3f std=%.3f | "
        "g_regional: min=%.2f max=%.2f mean=%.3f std=%.3f | "
        "g_residual: min=%.2f max=%.2f mean=%.3f std=%.3f",
        height_m, grid_step,
        x_min / 1e3, x_max / 1e3, z_min / 1e3, z_max / 1e3,
        g_grid.shape[0], g_grid.shape[1],
        float(np.min(g_data)), float(np.max(g_data)),
        float(np.mean(g_data)), float(np.std(g_data)),
        float(np.min(g_regional)), float(np.max(g_regional)),
        float(np.mean(g_regional)), float(np.std(g_regional)),
        float(np.min(g_residual)), float(np.max(g_residual)),
        float(np.mean(g_residual)), float(np.std(g_residual)),
    )

    return g_residual, g_regional, grid_info
