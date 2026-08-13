"""
truth_products — rasteriza la verdad a UNA malla concreta y calcula los derivados.

P1: la verdad es el World (geometría + propiedades). Los derivados NO se almacenan
junto a él: se calculan aquí, con una función pura, para la malla que se pida.
La malla es un ARGUMENTO, no una propiedad del mundo.
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from .contract import World

TRUTH_VERSION = "truth/1"


@dataclass(frozen=True)
class Mesh:
    """Malla regular. y positivo HACIA ABAJO (convención de TerraQuantum)."""
    nx: int
    ny: int
    nz: int
    block_m: float
    origin_m: tuple = (0.0, 0.0, 0.0)

    def centers(self):
        """Devuelve (x_c, y_c, z_c) aplanados en orden C: x varía más lento."""
        ox, oy, oz = self.origin_m
        x = ox + (np.arange(self.nx) + 0.5) * self.block_m
        y = oy + (np.arange(self.ny) + 0.5) * self.block_m
        z = oz + (np.arange(self.nz) + 0.5) * self.block_m
        xx, yy, zz = np.meshgrid(x, y, z, indexing="ij")
        return xx.ravel(), yy.ravel(), zz.ravel()

    @property
    def n_cells(self) -> int:
        return self.nx * self.ny * self.nz

    @property
    def cell_volume_m3(self) -> float:
        return self.block_m ** 3


@dataclass(frozen=True)
class TruthProducts:
    """Derivados calculados desde el World para una malla dada."""
    mesh: Mesh
    density_t_m3: np.ndarray        # densidad absoluta por celda
    contrast_t_m3: np.ndarray       # contraste respecto al fondo
    body_mask: np.ndarray           # bool: celda dentro de algún cuerpo
    body_id_per_cell: np.ndarray    # -1 = fondo, i = índice del cuerpo
    centroids_m: dict               # body_id -> (x, y, z) centroide VERDADERO
    volumes_m3: dict                # body_id -> volumen analítico
    top_depths_m: dict              # body_id -> profundidad del techo
    truth_version: str = TRUTH_VERSION


def truth_products(world: World, mesh: Mesh) -> TruthProducts:
    """Función PURA: mismo (world, mesh) -> mismo resultado, siempre."""
    x_c, y_c, z_c = mesh.centers()

    bg = world.properties.background
    density = np.full(x_c.size, bg.density_t_m3, dtype=np.float64)
    body_id = np.full(x_c.size, -1, dtype=np.int32)

    centroids, volumes, tops = {}, {}, {}

    for i, body in enumerate(world.geometry.bodies):
        inside = np.asarray(body.shape.contains(x_c, y_c, z_c), dtype=bool)
        props = world.properties.domains[body.domain]
        density[inside] = props.density_t_m3
        body_id[inside] = i

        # Centroide ANALÍTICO de la forma (no el rasterizado): la verdad no
        # depende de la resolución de la malla con la que se evalúe.
        shape = body.shape
        if shape.kind == "sphere":
            centroids[body.id] = (shape.cx_m, shape.cy_m, shape.cz_m)
        else:  # prism
            centroids[body.id] = (
                0.5 * (shape.x0_m + shape.x1_m),
                0.5 * (shape.y0_m + shape.y1_m),
                0.5 * (shape.z0_m + shape.z1_m),
            )
        volumes[body.id] = shape.volume_m3
        tops[body.id] = shape.top_depth_m

    return TruthProducts(
        mesh=mesh,
        density_t_m3=density,
        contrast_t_m3=density - bg.density_t_m3,
        body_mask=body_id >= 0,
        body_id_per_cell=body_id,
        centroids_m=centroids,
        volumes_m3=volumes,
        top_depths_m=tops,
    )
