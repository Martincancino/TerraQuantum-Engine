"""
octree_mesh_builder.py — Wrapper de producción para TreeMesh Octree (Sprint 3 cierre).

Encapsula los parámetros óptimos del Octree dado un survey y construye una
TreeMesh lista para inversión. Centraliza la lógica de calibración para que
ni geophysics_service ni grid_calculator necesiten conocer las reglas internas.

Reglas de calibración (Li & Oldenburg / SimPEG estándar):
  base_cell_size   = block_size_m  — pixel-perfect con grilla regular (TreeMesh.from_regular_grid)
  max_refine       = 2 (local) / 3 (regional: L_max > 50 km)
  refine_radius    = max(3 × mean_spacing, 2 × base)  — entorno de sensores
  min_cell_size    = max(base / 8, 5 m)  — evitar over-refinamiento degenerado
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

import numpy as np

from exploration.treemesh import TreeMesh

REGIONAL_SCALE_M = 50_000.0   # Survey > 50 km → régimen regional
LARGE_GRID_CELLS = 50_000     # nx·ny·nz > 50k → también activa auto-TreeMesh


@dataclass
class OctreeParams:
    """Parámetros calibrados para construir un TreeMesh dado un survey."""

    base_cell_size_m: float
    max_refinement_depth: int
    refine_radius_m: float
    min_cell_size_m: float
    n_sensors: int
    is_regional: bool
    rationale: list = field(default_factory=list)

    def as_dict(self) -> dict:
        return {
            "base_cell_size_m": self.base_cell_size_m,
            "max_refinement_depth": self.max_refinement_depth,
            "refine_radius_m": self.refine_radius_m,
            "min_cell_size_m": self.min_cell_size_m,
            "n_sensors": self.n_sensors,
            "is_regional": self.is_regional,
            "rationale": list(self.rationale),
        }


def compute_octree_params(
    block_size_m: float,
    x_extent_m: float,
    z_extent_m: float,
    mean_spacing_m: float,
    n_sensors: int,
) -> OctreeParams:
    """Calcula los parámetros óptimos del Octree para un survey dado.

    Parameters
    ----------
    block_size_m : float
        Tamaño de celda de la grilla regular (define la celda base del Octree).
    x_extent_m, z_extent_m : float
        Extensión horizontal del survey en metros.
    mean_spacing_m : float
        Espaciado medio entre sensores.
    n_sensors : int
        Número de sensores del survey.

    Returns
    -------
    OctreeParams
    """
    rationale: list[str] = []

    max_extent = max(float(x_extent_m), float(z_extent_m))
    is_regional = max_extent > REGIONAL_SCALE_M

    base_cell_size = float(block_size_m)
    rationale.append(
        f"base_cell_size = block_size_m ({base_cell_size:.1f} m) — "
        "pixel-perfect con grilla regular via TreeMesh.from_regular_grid."
    )

    max_refine = 3 if is_regional else 2
    rationale.append(
        f"max_refine = {max_refine} "
        f"({'regional' if is_regional else 'local'}: L_max = {max_extent / 1000:.1f} km, "
        f"umbral = {REGIONAL_SCALE_M / 1000:.0f} km)."
    )

    safe_spacing = max(float(mean_spacing_m), 1.0)
    refine_radius = max(3.0 * safe_spacing, 2.0 * base_cell_size)
    rationale.append(
        f"refine_radius = max(3 × spacing, 2 × base) = {refine_radius:.1f} m — "
        "garantiza refinamiento en el entorno inmediato de los sensores."
    )

    min_cell_size = max(base_cell_size / 8.0, 5.0)
    rationale.append(
        f"min_cell_size = max(base/8, 5 m) = {min_cell_size:.1f} m — "
        "evita celdas degeneradas por over-refinamiento."
    )

    return OctreeParams(
        base_cell_size_m=base_cell_size,
        max_refinement_depth=max_refine,
        refine_radius_m=refine_radius,
        min_cell_size_m=min_cell_size,
        n_sensors=int(n_sensors),
        is_regional=is_regional,
        rationale=rationale,
    )


def should_auto_use_treemesh(
    n_cells: int,
    x_extent_m: float,
    z_extent_m: float,
) -> bool:
    """Retorna True cuando el survey justifica usar TreeMesh como default.

    Criterios (cualquiera es suficiente):
      - Grilla regular supera LARGE_GRID_CELLS (50k celdas) — costo RAM/compute alto
      - Survey extent supera 50 km — régimen regional donde el Octree aporta
    """
    if n_cells > LARGE_GRID_CELLS:
        return True
    if max(float(x_extent_m), float(z_extent_m)) > REGIONAL_SCALE_M:
        return True
    return False


def build_treemesh_from_survey(
    block_size_m: float,
    nx: int,
    ny: int,
    nz: int,
    x_extent_m: float,
    z_extent_m: float,
    mean_spacing_m: float,
    sensor_coords: np.ndarray,
    max_refine_override: Optional[int] = None,
) -> tuple[TreeMesh, OctreeParams]:
    """Construye una TreeMesh de producción dado un survey.

    Parameters
    ----------
    block_size_m : float
        Tamaño de celda base (igual al de la grilla regular).
    nx, ny, nz : int
        Dimensiones de la grilla regular (definen los bounds físicos del dominio).
    x_extent_m, z_extent_m : float
        Extensión horizontal del survey en metros.
    mean_spacing_m : float
        Espaciado medio entre sensores (para calibrar refine_radius).
    sensor_coords : np.ndarray, shape (n, 3)
        Coordenadas [x, y, z] de los sensores en el sistema local del modelo.
    max_refine_override : int, optional
        Override de max_refinement_depth (None → regla automática de calibración).

    Returns
    -------
    (TreeMesh, OctreeParams)
        La malla construida y los parámetros usados.
    """
    n_sensors = len(sensor_coords) if sensor_coords is not None and len(sensor_coords) > 0 else 0
    octree_p = compute_octree_params(
        block_size_m=block_size_m,
        x_extent_m=x_extent_m,
        z_extent_m=z_extent_m,
        mean_spacing_m=mean_spacing_m,
        n_sensors=n_sensors,
    )

    effective_max_refine = (
        int(max_refine_override)
        if max_refine_override is not None
        else octree_p.max_refinement_depth
    )

    mesh = TreeMesh.from_regular_grid(
        nx=int(nx),
        ny=int(ny),
        nz=int(nz),
        block_size=float(block_size_m),
        max_refinement_depth=effective_max_refine,
        sensor_coords=sensor_coords if n_sensors > 0 else None,
        refine_radius=octree_p.refine_radius_m,
        min_cell_size=octree_p.min_cell_size_m,
    )

    return mesh, octree_p
