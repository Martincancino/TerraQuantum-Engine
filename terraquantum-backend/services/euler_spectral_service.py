"""F2B — Estimación de PROFUNDIDAD independiente de la inversión.

Dos métodos clásicos y complementarios (el puente a F11: priors de
profundidad que los campos potenciales solos no resuelven):

  1. DECONVOLUCIÓN DE EULER (ventana móvil, Reid et al. 1990): resuelve por
     mínimos cuadrados la ecuación de homogeneidad de Euler en ventanas de la
     grilla → nube de soluciones (x, y, profundidad) con criterio de
     aceptación estándar (incertidumbre relativa de z y pertenencia a la
     ventana). El índice estructural N lo elige el usuario:
       gravedad: 2=esfera, 1=cilindro, 0=contacto/losa
       magnetometría: 3=dipolo/esfera, 2=tubo, 1=dique, 0=contacto
  2. ESPECTRO DE POTENCIA RADIAL (método de dos pendientes): ln(P) vs |k|;
     la pendiente de cada tramo ≈ −2·z_ensamble → profundidad promedio de los
     ensambles profundo (k bajo) y somero (k alto). Chequeo cruzado de Euler.

HONESTIDAD de método (documentada en cada salida): Euler estima con ±15-25%
típico y depende del índice estructural; el espectro da profundidades de
ENSAMBLE (promedios), no de cuerpos individuales. Son ESTIMACIONES para
priors/targeting, no mediciones.

Convenciones: x=este, y=norte, z hacia ABAJO (profundidad positiva bajo el
plano de observación). Derivadas del utilitario FFT compartido.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import List, Optional, Tuple

import numpy as np

from core.logging import get_logger
from services.mag_enhancement_service import (
    first_vertical_derivative,
    horizontal_derivatives,
)
from services.potential_field_grid_service import ScatteredGrid

_log = get_logger(__name__)

METHOD_HONESTY_NOTE = (
    "Estimación de profundidad INDEPENDIENTE de la inversión (Euler ±15-25% "
    "típico, depende del índice estructural; espectro = profundidad promedio "
    "de ensamble). Úsela como prior/targeting y chequeo cruzado, no como medición."
)


@dataclass
class EulerSolution:
    x_m: float
    y_m: float
    depth_m: float
    background: float
    rel_uncertainty: float


@dataclass
class EulerResult:
    solutions: List[EulerSolution] = field(default_factory=list)
    structural_index: float = 3.0
    n_windows: int = 0
    n_accepted: int = 0
    report: dict = field(default_factory=dict)


def euler_deconvolution(
    sg: ScatteredGrid,
    structural_index: float = 3.0,
    window_cells: int = 10,
    step_cells: int = 2,
    max_depth_m: Optional[float] = None,
    max_rel_uncertainty: float = 0.15,
    min_signal_percentile: float = 90.0,
) -> EulerResult:
    """Euler por ventana móvil sobre la grilla (gravedad o TMI).

    Acepta una solución si: la ventana tiene SEÑAL (gradiente RMS sobre el
    percentil `min_signal_percentile` de todas las ventanas — Euler solo
    donde hay anomalía; en campo lejano casi nulo dominan los errores de
    discretización y salen profundidades espurias); profundidad ∈
    (0, max_depth]; incertidumbre relativa de z ≤ max_rel_uncertainty
    (criterio estándar de Reid); y la posición horizontal cae dentro de la
    ventana ampliada (irse lejos de su ventana es extrapolación sin soporte).
    """
    if not (0.0 <= structural_index <= 3.0):
        raise ValueError(
            f"Índice estructural fuera de rango: {structural_index}. Use 0-3 "
            "(grav: 2=esfera, 1=cilindro, 0=contacto; mag: 3=dipolo, 2=tubo, "
            "1=dique, 0=contacto)."
        )
    grid = sg.values
    ny, nx = grid.shape
    if window_cells < 4 or window_cells > min(nx, ny):
        raise ValueError(
            f"window_cells={window_cells} inválido para una grilla {nx}×{ny} "
            "(mínimo 4, máximo el lado menor de la grilla)."
        )
    if max_depth_m is None:
        max_depth_m = 0.5 * max(nx * sg.dx, ny * sg.dy)   # regla del pulgar

    gx, gy = horizontal_derivatives(grid, sg.dx, sg.dy)
    gz = first_vertical_derivative(grid, sg.dx, sg.dy)   # ∂/∂z hacia abajo

    X = sg.x0 + np.arange(nx) * sg.dx
    Y = sg.y0 + np.arange(ny) * sg.dy
    XX, YY = np.meshgrid(X, Y)

    N = float(structural_index)

    # Umbral de SEÑAL por ventana: gradiente RMS ≥ percentil de todas.
    grad_rms = np.sqrt(gx * gx + gy * gy + gz * gz)
    window_rms = []
    window_index = []
    for iy in range(0, ny - window_cells + 1, step_cells):
        for ix in range(0, nx - window_cells + 1, step_cells):
            sl = (slice(iy, iy + window_cells), slice(ix, ix + window_cells))
            window_rms.append(float(np.sqrt(np.mean(grad_rms[sl] ** 2))))
            window_index.append((iy, ix))
    signal_threshold = float(np.percentile(window_rms, min_signal_percentile))

    sols: List[EulerSolution] = []
    n_windows = 0
    for w, (iy, ix) in enumerate(window_index):
        if True:
            n_windows += 1
            if window_rms[w] < signal_threshold:
                continue
            sl = (slice(iy, iy + window_cells), slice(ix, ix + window_cells))
            tx = gx[sl].ravel()
            ty = gy[sl].ravel()
            tz = gz[sl].ravel()
            t = grid[sl].ravel()
            xw = XX[sl].ravel()
            yw = YY[sl].ravel()

            # Ecuación de homogeneidad de Euler, TODO en z hacia abajo
            # (obs en z=0, fuente en z0>0, Tz = ∂T/∂z_abajo):
            #   (x−x0)Tx + (y−y0)Ty + (0−z0)Tz = −N(T−B)
            # → Tx·x0 + Ty·y0 + Tz·z0 + N·B = x·Tx + y·Ty + N·T
            A = np.column_stack([tx, ty, tz, N * np.ones_like(t)])
            b = xw * tx + yw * ty + N * t
            try:
                sol, residuals, rank, _ = np.linalg.lstsq(A, b, rcond=None)
            except np.linalg.LinAlgError:
                continue
            if rank < 4:
                continue
            x0, y0, z0, B = (float(v) for v in sol)

            # Incertidumbre de z0 desde la covarianza de mínimos cuadrados.
            dof = len(b) - 4
            if dof <= 0:
                continue
            rss = float(residuals[0]) if len(residuals) else float(
                np.sum((A @ sol - b) ** 2)
            )
            try:
                cov = np.linalg.inv(A.T @ A) * (rss / dof)
            except np.linalg.LinAlgError:
                continue
            sigma_z = float(np.sqrt(max(cov[2, 2], 0.0)))

            if not (0.0 < z0 <= max_depth_m):
                continue
            rel = sigma_z / z0
            if rel > max_rel_uncertainty:
                continue
            # La solución debe caer en la ventana ampliada (±50%).
            wx0, wx1 = X[ix], X[ix + window_cells - 1]
            wy0, wy1 = Y[iy], Y[iy + window_cells - 1]
            mx = 0.5 * (wx1 - wx0)
            my = 0.5 * (wy1 - wy0)
            if not (wx0 - mx <= x0 <= wx1 + mx and wy0 - my <= y0 <= wy1 + my):
                continue
            sols.append(EulerSolution(x0, y0, z0, B, rel))

    report = {
        "structural_index": N,
        "window_cells": window_cells,
        "step_cells": step_cells,
        "max_depth_m": float(max_depth_m),
        "max_rel_uncertainty": max_rel_uncertainty,
        "min_signal_percentile": min_signal_percentile,
        "n_windows": n_windows,
        "n_accepted": len(sols),
        "acceptance_rate": (len(sols) / n_windows) if n_windows else 0.0,
        "honesty_note": METHOD_HONESTY_NOTE,
    }
    if sols:
        depths = np.array([s.depth_m for s in sols])
        report["depth_median_m"] = float(np.median(depths))
        report["depth_p25_m"] = float(np.percentile(depths, 25))
        report["depth_p75_m"] = float(np.percentile(depths, 75))
    _log.info("euler_deconvolution", n_windows=n_windows, n_accepted=len(sols))
    return EulerResult(
        solutions=sols, structural_index=N,
        n_windows=n_windows, n_accepted=len(sols), report=report,
    )


def radial_power_spectrum(
    sg: ScatteredGrid, n_bins: int = 40
) -> dict:
    """Espectro de potencia radialmente promediado + profundidades de ensamble.

    ln(P(k)) con pendiente ≈ −2·z: el tramo de k BAJO da la profundidad del
    ensamble profundo; el de k ALTO, el somero (método clásico de dos
    pendientes). El quiebre se elige minimizando el RSS de las dos rectas.
    """
    grid = sg.values - float(sg.values.mean())
    ny, nx = grid.shape
    F = np.fft.fft2(grid * np.hanning(ny)[:, None] * np.hanning(nx)[None, :])
    P = np.abs(F) ** 2
    kx = 2.0 * np.pi * np.fft.fftfreq(nx, d=sg.dx)
    ky = 2.0 * np.pi * np.fft.fftfreq(ny, d=sg.dy)
    KX, KY = np.meshgrid(kx, ky)
    K = np.sqrt(KX * KX + KY * KY).ravel()
    Pf = P.ravel()

    k_max = float(K.max()) * 0.7            # descarta la esquina de Nyquist
    k_min = 2.0 * np.pi / (0.9 * max(nx * sg.dx, ny * sg.dy))
    ok = (K > k_min) & (K < k_max) & (Pf > 0)
    if int(ok.sum()) < 3 * n_bins:
        n_bins = max(8, int(ok.sum()) // 3)
    edges = np.linspace(k_min, k_max, n_bins + 1)
    kc, lnp = [], []
    for i in range(n_bins):
        m = ok & (K >= edges[i]) & (K < edges[i + 1])
        if int(m.sum()) >= 3:
            kc.append(0.5 * (edges[i] + edges[i + 1]))
            lnp.append(float(np.log(Pf[m].mean())))
    kc_arr = np.array(kc)
    lnp_arr = np.array(lnp)
    if len(kc_arr) < 8:
        raise ValueError(
            "Grilla demasiado chica para un espectro radial útil (menos de 8 "
            "bandas de número de onda con datos)."
        )

    # Dos pendientes: quiebre que minimiza el RSS total (≥4 puntos por tramo).
    best = None
    for br in range(4, len(kc_arr) - 4):
        s1, i1 = np.polyfit(kc_arr[:br], lnp_arr[:br], 1)
        s2, i2 = np.polyfit(kc_arr[br:], lnp_arr[br:], 1)
        rss = float(np.sum((lnp_arr[:br] - (s1 * kc_arr[:br] + i1)) ** 2)
                    + np.sum((lnp_arr[br:] - (s2 * kc_arr[br:] + i2)) ** 2))
        if best is None or rss < best[0]:
            best = (rss, br, s1, s2)
    _, br, slope_deep, slope_shallow = best

    depth_deep = max(0.0, -float(slope_deep) / 2.0)
    depth_shallow = max(0.0, -float(slope_shallow) / 2.0)
    return {
        "k_rad_per_m": kc_arr.tolist(),
        "ln_power": lnp_arr.tolist(),
        "break_index": int(br),
        "ensemble_depth_deep_m": depth_deep,
        "ensemble_depth_shallow_m": depth_shallow,
        "honesty_note": METHOD_HONESTY_NOTE,
    }
