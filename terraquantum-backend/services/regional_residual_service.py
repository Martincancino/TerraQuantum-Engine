"""F2B — Separación REGIONAL-RESIDUAL como producto de USUARIO.

Dos métodos estándar de gabinete:
  - "polynomial": superficie de tendencia por mínimos cuadrados (orden 1-3).
    El regional es el polinomio ajustado; el residual, lo que queda.
  - "upward_continuation": el regional es el campo continuado a una altura
    elegida (retiene fuentes profundas/anchas); residual = obs − regional.

ADVERTENCIA MEDIDA (memoria del proyecto, no re-litigar): la separación
regional NO se aplica automática antes de invertir — medido que no cura el
sink de LdM y DEGRADÓ DO-27. Es un producto de MAPA y de decisión del
usuario; cada resultado lleva esta advertencia.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import List, Optional

import numpy as np

from core.logging import get_logger
from services.potential_field_grid_service import (
    ScatteredGrid,
    grid_scattered,
    sample_grid,
    upward_continue_grid,
)

_log = get_logger(__name__)

VALID_METHODS = ("polynomial", "upward_continuation")

MEASURED_WARNING = (
    "Producto de mapa/decisión del usuario: la separación regional NO se "
    "aplica automática antes de invertir (medido en este proyecto: no corrige "
    "los artefactos profundos de LdM y degradó el benchmark DO-27). Úsela "
    "para interpretar, no como preproceso ciego."
)


@dataclass
class RegionalResidualResult:
    regional: np.ndarray            # por estación
    residual: np.ndarray            # por estación
    method: str
    report: dict = field(default_factory=dict)
    grid: Optional[ScatteredGrid] = None            # grilla del CAMPO observado
    regional_grid: Optional[np.ndarray] = None      # (ny, nx)
    residual_grid: Optional[np.ndarray] = None      # (ny, nx)


def _poly_design(x: np.ndarray, y: np.ndarray, order: int) -> np.ndarray:
    cols = []
    for total in range(order + 1):
        for j in range(total + 1):
            i = total - j
            cols.append((x ** i) * (y ** j))
    return np.column_stack(cols)


def separate_regional_residual(
    x_m: np.ndarray,
    y_m: np.ndarray,
    values: np.ndarray,
    method: str = "polynomial",
    order: int = 1,
    height_m: float = 2000.0,
    with_grids: bool = True,
) -> RegionalResidualResult:
    """Separa regional/residual por estación (+ grillas para mapas).

    `values` en la unidad del dato (mGal o nT); la separación es lineal y
    respeta la unidad. Errores de input → ValueError con acción (ES).
    """
    if method not in VALID_METHODS:
        raise ValueError(
            f"Método desconocido: '{method}'. Use 'polynomial' (tendencia de "
            "orden 1-3) o 'upward_continuation' (regional = campo continuado)."
        )
    x = np.asarray(x_m, dtype=float)
    y = np.asarray(y_m, dtype=float)
    v = np.asarray(values, dtype=float)
    if not (len(x) == len(y) == len(v)):
        raise ValueError("x, y y valores deben tener el mismo largo.")
    ok = np.isfinite(x) & np.isfinite(y) & np.isfinite(v)
    if int(ok.sum()) < 8:
        raise ValueError(
            f"Se necesitan ≥8 estaciones válidas para separar regional-residual "
            f"(hay {int(ok.sum())})."
        )

    report: dict = {"method": method, "n_stations": int(ok.sum()),
                    "warnings": [MEASURED_WARNING]}

    if method == "polynomial":
        if not (1 <= int(order) <= 3):
            raise ValueError(
                f"Orden de tendencia fuera de rango: {order}. Use 1 (plano), "
                "2 (cuadrática) o 3 (cúbica); órdenes mayores absorben la señal local."
            )
        order = int(order)
        # Coordenadas centradas/escaladas: condicionamiento del ajuste.
        xc, yc = x[ok] - x[ok].mean(), y[ok] - y[ok].mean()
        scale = max(xc.std(), yc.std(), 1.0)
        A = _poly_design(xc / scale, yc / scale, order)
        coef, *_ = np.linalg.lstsq(A, v[ok], rcond=None)
        regional_ok = A @ coef

        regional = np.full_like(v, np.nan)
        regional[ok] = regional_ok
        residual = v - regional

        ss_res = float(np.sum((v[ok] - regional_ok) ** 2))
        ss_tot = float(np.sum((v[ok] - v[ok].mean()) ** 2))
        report.update({
            "order": order,
            "r2": (1.0 - ss_res / ss_tot) if ss_tot > 0 else 1.0,
            "residual_rms": float(np.sqrt(np.mean((v[ok] - regional_ok) ** 2))),
        })

        grid = regional_grid = residual_grid = None
        if with_grids:
            grid = grid_scattered(x[ok], y[ok], v[ok])
            XXc = (grid.xi[None, :] - x[ok].mean()) / scale
            YYc = (grid.yi[:, None] - y[ok].mean()) / scale
            XX, YY = np.meshgrid(XXc.ravel(), YYc.ravel())
            regional_grid = (_poly_design(XX.ravel(), YY.ravel(), order) @ coef).reshape(
                grid.ny, grid.nx
            )
            residual_grid = grid.values - regional_grid
            report["grid"] = grid.meta()
    else:
        if height_m <= 0:
            raise ValueError(
                "upward_continuation requiere height_m > 0 (altura de "
                "continuación en metros; típico: 1-10× el espaciamiento)."
            )
        grid = grid_scattered(x[ok], y[ok], v[ok])
        regional_grid = upward_continue_grid(grid.values, grid.dx, grid.dy, height_m)
        residual_grid = grid.values - regional_grid
        regional = np.full_like(v, np.nan)
        regional[ok] = sample_grid(
            ScatteredGrid(
                values=regional_grid, x0=grid.x0, y0=grid.y0, dx=grid.dx,
                dy=grid.dy, nx=grid.nx, ny=grid.ny, inside_hull=grid.inside_hull,
            ),
            x[ok], y[ok],
        )
        residual = v - regional
        report.update({
            "height_m": float(height_m),
            "grid": grid.meta(),
            "residual_rms": float(np.sqrt(np.nanmean(residual[ok] ** 2))),
        })
        report["warnings"].extend(grid.warnings)

    _log.info("regional_residual", method=method, n=report["n_stations"])
    return RegionalResidualResult(
        regional=regional, residual=residual, method=method, report=report,
        grid=grid, regional_grid=regional_grid, residual_grid=residual_grid,
    )


def result_to_csv(
    station_ids: List[str],
    x_m: np.ndarray,
    y_m: np.ndarray,
    values: np.ndarray,
    res: RegionalResidualResult,
    value_name: str = "valor",
) -> str:
    """CSV descargable del producto (una fila por estación)."""
    lines = [
        f"# TerraQuantum regional-residual — método: {res.method}",
        f"# {MEASURED_WARNING}",
        f"station_id,x_m,y_m,{value_name},regional,residual",
    ]
    for i in range(len(values)):
        lines.append(
            f"{station_ids[i]},{x_m[i]:.3f},{y_m[i]:.3f},{values[i]:.6f},"
            f"{res.regional[i]:.6f},{res.residual[i]:.6f}"
        )
    return "\n".join(lines) + "\n"
