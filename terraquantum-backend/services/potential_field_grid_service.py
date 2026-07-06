"""F2B — Utilitario de GRILLA para campos potenciales (compartido).

Base de los productos de gabinete que operan en el dominio de la grilla/FFT:
separación regional-residual por continuación ascendente (F2B.4) y la suite
de realce magnético (RTP/derivadas/continuación, F2B.5).

Solo numpy/scipy (sin dependencias nuevas). Convenciones:
  - x = este [m], y = norte [m] (coordenadas ya métricas del import).
  - La grilla es regular (dx=dy por defecto), interpolación lineal de
    scipy.griddata con relleno nearest FUERA del casco convexo (reportado:
    los bordes extrapolados son menos confiables y se dice).
  - FFT con padding espejado (reduce el wrap-around; estándar del dominio).

Oráculo analítico de la continuación (en tests): para un armónico puro
cos(k·x), la continuación ascendente a altura h multiplica por exp(−|k|·h)
EXACTAMENTE — cualquier error de convención de FFT rompe ese test.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import List, Optional, Tuple

import numpy as np
from scipy.interpolate import griddata

from core.logging import get_logger

_log = get_logger(__name__)


@dataclass
class ScatteredGrid:
    """Grilla regular construida desde estaciones dispersas."""

    values: np.ndarray          # (ny, nx)
    x0: float
    y0: float
    dx: float
    dy: float
    nx: int
    ny: int
    inside_hull: np.ndarray     # (ny, nx) bool — True = interpolado (confiable)
    warnings: List[str] = field(default_factory=list)

    @property
    def xi(self) -> np.ndarray:
        return self.x0 + np.arange(self.nx) * self.dx

    @property
    def yi(self) -> np.ndarray:
        return self.y0 + np.arange(self.ny) * self.dy

    def meta(self) -> dict:
        return {
            "nx": self.nx, "ny": self.ny,
            "x0": self.x0, "y0": self.y0,
            "dx": self.dx, "dy": self.dy,
            "outside_hull_fraction": float(1.0 - self.inside_hull.mean()),
            "warnings": list(self.warnings),
        }


def grid_scattered(
    x_m: np.ndarray,
    y_m: np.ndarray,
    values: np.ndarray,
    target_nx: int = 128,
    max_nodes: int = 512,
) -> ScatteredGrid:
    """Grilla regular desde estaciones dispersas (lineal + nearest fuera del casco).

    El espaciamiento sale del extent y `target_nx` (acotado para que la FFT
    sea liviana). Lanza ValueError claro con <8 estaciones o extent nulo.
    """
    x = np.asarray(x_m, dtype=float)
    y = np.asarray(y_m, dtype=float)
    v = np.asarray(values, dtype=float)
    ok = np.isfinite(x) & np.isfinite(y) & np.isfinite(v)
    x, y, v = x[ok], y[ok], v[ok]
    if len(v) < 8:
        raise ValueError(
            f"Se necesitan ≥8 estaciones finitas para grillar (hay {len(v)})."
        )
    span_x = float(x.max() - x.min())
    span_y = float(y.max() - y.min())
    if span_x <= 0 or span_y <= 0:
        raise ValueError(
            "El survey es una línea o un punto (extent cero en x o y): los "
            "productos de grilla requieren cobertura 2D."
        )

    nx = int(min(max(16, target_nx), max_nodes))
    dx = span_x / (nx - 1)
    ny = int(min(max(16, round(span_y / dx) + 1), max_nodes))
    dy = span_y / (ny - 1)

    xi = x.min() + np.arange(nx) * dx
    yi = y.min() + np.arange(ny) * dy
    XX, YY = np.meshgrid(xi, yi)

    linear = griddata((x, y), v, (XX, YY), method="linear")
    nearest = griddata((x, y), v, (XX, YY), method="nearest")
    inside = np.isfinite(linear)
    grid = np.where(inside, linear, nearest)

    warnings: List[str] = []
    out_frac = float(1.0 - inside.mean())
    if out_frac > 0.25:
        warnings.append(
            f"{out_frac:.0%} de la grilla queda FUERA del casco de estaciones "
            "(relleno nearest): los bordes del mapa son extrapolación y valen "
            "menos que el interior."
        )
    return ScatteredGrid(
        values=grid, x0=float(x.min()), y0=float(y.min()),
        dx=float(dx), dy=float(dy), nx=nx, ny=ny,
        inside_hull=inside, warnings=warnings,
    )


def sample_grid(sg: ScatteredGrid, x_m: np.ndarray, y_m: np.ndarray) -> np.ndarray:
    """Muestreo bilineal de la grilla en las posiciones de las estaciones."""
    x = np.asarray(x_m, dtype=float)
    y = np.asarray(y_m, dtype=float)
    fx = np.clip((x - sg.x0) / sg.dx, 0, sg.nx - 1)
    fy = np.clip((y - sg.y0) / sg.dy, 0, sg.ny - 1)
    ix = np.clip(np.floor(fx).astype(int), 0, sg.nx - 2)
    iy = np.clip(np.floor(fy).astype(int), 0, sg.ny - 2)
    tx = fx - ix
    ty = fy - iy
    g = sg.values
    return (
        g[iy, ix] * (1 - tx) * (1 - ty)
        + g[iy, ix + 1] * tx * (1 - ty)
        + g[iy + 1, ix] * (1 - tx) * ty
        + g[iy + 1, ix + 1] * tx * ty
    )


def _padded_fft2(grid: np.ndarray) -> "Tuple[np.ndarray, Tuple[int, int], Tuple[int, int]]":
    """FFT 2D con padding espejado (mitad del tamaño por lado)."""
    ny, nx = grid.shape
    py, px = ny // 2, nx // 2
    padded = np.pad(grid, ((py, py), (px, px)), mode="reflect")
    return np.fft.fft2(padded), (py, px), padded.shape


def _wavenumbers(shape: "Tuple[int, int]", dx: float, dy: float):
    ny, nx = shape
    kx = 2.0 * np.pi * np.fft.fftfreq(nx, d=dx)
    ky = 2.0 * np.pi * np.fft.fftfreq(ny, d=dy)
    KX, KY = np.meshgrid(kx, ky)
    return KX, KY, np.sqrt(KX * KX + KY * KY)


def apply_fft_filter(
    grid: np.ndarray, dx: float, dy: float, factor_fn
) -> np.ndarray:
    """Aplica un filtro en el dominio del número de onda con padding espejado.

    `factor_fn(KX, KY, K)` devuelve el factor complejo por componente. La
    parte real del resultado se recorta al tamaño original.
    """
    F, (py, px), pshape = _padded_fft2(grid)
    KX, KY, K = _wavenumbers(pshape, dx, dy)
    out = np.real(np.fft.ifft2(F * factor_fn(KX, KY, K)))
    ny, nx = grid.shape
    return out[py:py + ny, px:px + nx]


def upward_continue_grid(
    grid: np.ndarray, dx: float, dy: float, height_m: float
) -> np.ndarray:
    """Continuación ascendente a `height_m` (atenúa lo somero/corto).

    Factor exacto de teoría de potencial: exp(−|k|·h). h<0 (descendente) se
    rechaza: amplifica ruido sin control y no es un producto de gabinete.
    """
    if height_m < 0:
        raise ValueError(
            "La continuación DESCENDENTE (height_m<0) amplifica el ruido "
            "exponencialmente y no se ofrece como producto. Use height_m ≥ 0."
        )
    if height_m == 0:
        return grid.copy()
    return apply_fft_filter(grid, dx, dy, lambda KX, KY, K: np.exp(-K * height_m))
