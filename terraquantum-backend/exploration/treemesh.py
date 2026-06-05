"""
TreeMesh — Adaptive Octree grid for TerraQuantum (Sprint 3A — Foundation).
============================================================================

Reemplaza la grilla regular nx×ny×nz por una malla Octree adaptativa:
celdas pequeñas cerca de sensores, celdas grandes en el campo lejano. Permite
escalar el número de celdas SIN explosión de RAM (refinamiento dirigido).

Convención espacial (idéntica a exploration/checkerboard_test.build_voxel_grid):
    - x: eje horizontal
    - y: profundidad positiva hacia abajo
    - z: eje horizontal
    - Orden Fortran de la grilla base: índice = ix + nx·iy + nx·ny·iz
      con centro = (i + 0.5)·block_size  (pixel-perfect vs build_voxel_grid).

ALCANCE Sprint 3A (Foundation):
    - Estructura de datos (bounds por celda, centros, volúmenes, profundidades).
    - Refinamiento Octree dirigido por sensores (split 8-way conserva volumen).
    - El FORWARD (GravimetryForward) ya consume centros + tamaños por celda.
    - NO toca regularización ni el solver (Laplaciano Octree es Sprint 3B).

El estado de cada celda se almacena como una fila de bounds:
    cell = [x_min, x_max, y_min, y_max, z_min, z_max]
El split Octree (8 hijos) reparte cada eje a la mitad, por lo que la suma de
volúmenes es EXACTAMENTE el volumen del dominio en cualquier nivel de refinamiento.
"""

from __future__ import annotations

from typing import Optional, Tuple

import numpy as np
import scipy.sparse as sp

try:
    from scipy.spatial import cKDTree
except ImportError:  # pragma: no cover - scipy es dependencia dura del backend
    cKDTree = None


class TreeMesh:
    """
    Malla Octree adaptativa 3D.

    Parameters
    ----------
    x_bounds, y_bounds, z_bounds : (float, float)
        Límites físicos del dominio en metros. y es profundidad (positivo abajo).
    base_cell_size : float
        Resolución de la grilla base (celda raíz del octree), en metros.
    max_refinement_depth : int
        Número máximo de niveles de subdivisión (0 = grilla regular pura).
    sensor_coords : np.ndarray, optional
        (n, 3) coordenadas [x, y, z] de sensores que guían el refinamiento.
    refine_radius : float, optional
        Una celda se refina si la distancia de su centro al sensor más cercano
        es ≤ refine_radius. Default = 2 · base_cell_size.
    min_cell_size : float, optional
        Cota inferior del tamaño de celda: no se subdivide si el hijo quedaría
        por debajo de este tamaño. None = sin cota (solo limita max_refinement_depth).
    """

    def __init__(
        self,
        x_bounds: Tuple[float, float],
        y_bounds: Tuple[float, float],
        z_bounds: Tuple[float, float],
        base_cell_size: float = 4000.0,
        max_refinement_depth: int = 0,
        sensor_coords: Optional[np.ndarray] = None,
        refine_radius: Optional[float] = None,
        min_cell_size: Optional[float] = None,
    ):
        self.x_bounds = (float(x_bounds[0]), float(x_bounds[1]))
        self.y_bounds = (float(y_bounds[0]), float(y_bounds[1]))
        self.z_bounds = (float(z_bounds[0]), float(z_bounds[1]))
        self.base_cell_size = float(base_cell_size)
        self.max_refinement_depth = int(max_refinement_depth)
        self.min_cell_size = None if min_cell_size is None else float(min_cell_size)

        if self.base_cell_size <= 0:
            raise ValueError("base_cell_size debe ser mayor que 0.")
        if self.x_bounds[1] <= self.x_bounds[0] \
                or self.y_bounds[1] <= self.y_bounds[0] \
                or self.z_bounds[1] <= self.z_bounds[0]:
            raise ValueError("Los bounds deben cumplir min < max en cada eje.")

        self.sensor_coords = (
            None if sensor_coords is None
            else np.asarray(sensor_coords, dtype=np.float64)
        )
        self.refine_radius = (
            2.0 * self.base_cell_size if refine_radius is None
            else float(refine_radius)
        )

        # cells: (n_cells, 6) float64 = [x0, x1, y0, y1, z0, z1]
        # levels: (n_cells,) int — nivel de refinamiento (0 = celda base)
        self._cells = self._build_coarse_grid()
        self._levels = np.zeros(self._cells.shape[0], dtype=np.int32)

        if self.sensor_coords is not None and self.max_refinement_depth > 0:
            self._refine_near_sensors()

    # ── Construcción de fábrica ───────────────────────────────────────────────
    @classmethod
    def from_regular_grid(
        cls,
        nx: int,
        ny: int,
        nz: int,
        block_size: float,
        max_refinement_depth: int = 0,
        sensor_coords: Optional[np.ndarray] = None,
        refine_radius: Optional[float] = None,
        min_cell_size: Optional[float] = None,
    ) -> "TreeMesh":
        """
        Construye una TreeMesh cuya grilla base coincide EXACTAMENTE (centros y
        orden Fortran) con checkerboard_test.build_voxel_grid(nx, ny, nz, block_size).

        Garantía pixel-perfect: con max_refinement_depth=0, get_cell_centers()
        devuelve los mismos centros, en el mismo orden, que build_voxel_grid.
        """
        nx, ny, nz = int(nx), int(ny), int(nz)
        if nx <= 0 or ny <= 0 or nz <= 0:
            raise ValueError("nx, ny y nz deben ser mayores que 0.")
        bs = float(block_size)
        mesh = cls(
            x_bounds=(0.0, nx * bs),
            y_bounds=(0.0, ny * bs),
            z_bounds=(0.0, nz * bs),
            base_cell_size=bs,
            max_refinement_depth=max_refinement_depth,
            sensor_coords=sensor_coords,
            refine_radius=refine_radius,
            min_cell_size=min_cell_size,
        )
        return mesh

    # ── Construcción interna ──────────────────────────────────────────────────
    def _build_coarse_grid(self) -> np.ndarray:
        """
        Grilla base regular en orden Fortran (ix más rápido), idéntica a
        build_voxel_grid. El dominio se cubre con celdas de base_cell_size; el
        número de celdas por eje se redondea para cubrir exactamente el bound.
        """
        x0, x1 = self.x_bounds
        y0, y1 = self.y_bounds
        z0, z1 = self.z_bounds
        bs = self.base_cell_size

        nx = max(1, int(round((x1 - x0) / bs)))
        ny = max(1, int(round((y1 - y0) / bs)))
        nz = max(1, int(round((z1 - z0) / bs)))

        ix_g, iy_g, iz_g = np.mgrid[0:nx, 0:ny, 0:nz]
        ix = ix_g.ravel(order="F").astype(np.float64)
        iy = iy_g.ravel(order="F").astype(np.float64)
        iz = iz_g.ravel(order="F").astype(np.float64)

        cx0 = x0 + ix * bs
        cy0 = y0 + iy * bs
        cz0 = z0 + iz * bs

        cells = np.column_stack([
            cx0, cx0 + bs,
            cy0, cy0 + bs,
            cz0, cz0 + bs,
        ]).astype(np.float64)
        return cells

    def _refine_near_sensors(self) -> None:
        """
        Subdivide (split Octree 8-way) las celdas cuyo centro está a ≤ refine_radius
        del sensor más cercano, hasta max_refinement_depth o min_cell_size.

        El split reparte cada eje a la mitad: 8 hijos llenan exactamente la celda
        padre → la suma de volúmenes se conserva en todo momento.
        """
        if cKDTree is None:
            raise ImportError("scipy.spatial.cKDTree no disponible para refinamiento.")

        tree = cKDTree(self.sensor_coords)

        for _ in range(self.max_refinement_depth):
            centers = self._centers_of(self._cells)
            sizes = self._min_extent_of(self._cells)

            dist, _ = tree.query(centers, k=1)
            within = dist <= self.refine_radius
            can_split = self._levels < self.max_refinement_depth
            if self.min_cell_size is not None:
                can_split &= (sizes / 2.0) >= self.min_cell_size

            to_split = within & can_split
            if not np.any(to_split):
                break

            keep_cells = self._cells[~to_split]
            keep_lvls = self._levels[~to_split]
            child_cells = self._split_octree(self._cells[to_split])
            child_lvls = np.repeat(self._levels[to_split] + 1, 8)

            self._cells = np.vstack([keep_cells, child_cells])
            self._levels = np.concatenate([keep_lvls, child_lvls])

    @staticmethod
    def _split_octree(cells: np.ndarray) -> np.ndarray:
        """Divide cada celda (k, 6) en 8 octantes → (8k, 6). Conserva volumen."""
        if cells.shape[0] == 0:
            return cells.reshape(0, 6)

        x0, x1 = cells[:, 0], cells[:, 1]
        y0, y1 = cells[:, 2], cells[:, 3]
        z0, z1 = cells[:, 4], cells[:, 5]
        xm = 0.5 * (x0 + x1)
        ym = 0.5 * (y0 + y1)
        zm = 0.5 * (z0 + z1)

        children = []
        for sx in (0, 1):
            cx0 = x0 if sx == 0 else xm
            cx1 = xm if sx == 0 else x1
            for sy in (0, 1):
                cy0 = y0 if sy == 0 else ym
                cy1 = ym if sy == 0 else y1
                for sz in (0, 1):
                    cz0 = z0 if sz == 0 else zm
                    cz1 = zm if sz == 0 else z1
                    children.append(np.column_stack([cx0, cx1, cy0, cy1, cz0, cz1]))
        # Intercalar por celda padre: los 8 hijos quedan contiguos en la salida.
        stacked = np.stack(children, axis=1)        # (k, 8, 6)
        return stacked.reshape(-1, 6).astype(np.float64)

    # ── Helpers geométricos ───────────────────────────────────────────────────
    @staticmethod
    def _centers_of(cells: np.ndarray) -> np.ndarray:
        cx = 0.5 * (cells[:, 0] + cells[:, 1])
        cy = 0.5 * (cells[:, 2] + cells[:, 3])
        cz = 0.5 * (cells[:, 4] + cells[:, 5])
        return np.column_stack([cx, cy, cz]).astype(np.float64)

    @staticmethod
    def _sizes_of(cells: np.ndarray) -> np.ndarray:
        dx = cells[:, 1] - cells[:, 0]
        dy = cells[:, 3] - cells[:, 2]
        dz = cells[:, 5] - cells[:, 4]
        return np.column_stack([dx, dy, dz]).astype(np.float64)

    @staticmethod
    def _min_extent_of(cells: np.ndarray) -> np.ndarray:
        dx = cells[:, 1] - cells[:, 0]
        dy = cells[:, 3] - cells[:, 2]
        dz = cells[:, 5] - cells[:, 4]
        return np.minimum(np.minimum(dx, dy), dz)

    # ── API pública ───────────────────────────────────────────────────────────
    def get_cell_centers(self) -> np.ndarray:
        """(n_cells, 3) — centros [x, y, z] de cada celda."""
        return self._centers_of(self._cells)

    def get_cell_sizes(self) -> np.ndarray:
        """(n_cells, 3) — extensiones [dx, dy, dz] de cada celda."""
        return self._sizes_of(self._cells)

    def get_cell_volumes(self) -> np.ndarray:
        """(n_cells,) — volumen Δx·Δy·Δz de cada celda."""
        s = self._sizes_of(self._cells)
        return (s[:, 0] * s[:, 1] * s[:, 2]).astype(np.float64)

    def get_cell_depths(self) -> np.ndarray:
        """(n_cells,) — profundidad (centro y) de cada celda."""
        return (0.5 * (self._cells[:, 2] + self._cells[:, 3])).astype(np.float64)

    def get_cell_bounds(self) -> np.ndarray:
        """(n_cells, 6) — copia de [x0,x1,y0,y1,z0,z1] por celda."""
        return self._cells.copy()

    # ── Regularización Octree (Sprint 3B) ─────────────────────────────────────
    def build_laplacian_octree(self) -> "sp.csr_matrix":
        """
        SPRINT 3B — Laplaciano disperso para la malla Octree adaptativa.

        Construye un grafo de adyacencia POR CARAS (face-adjacency) entre celdas,
        soportando vecinos cross-level (una celda grande acoplada a varias pequeñas
        que comparten parcialmente su cara — nodos colgantes del octree).

        Peso de arista (idéntica convención a GravimetryInversion._build_laplacian
        en su ruta de tensor mesh, F0.9):

            w_ij = 2 / (h_i + h_j)

        donde h_i, h_j son las extensiones de las celdas i, j a lo largo del eje en
        el que se tocan. (h_i + h_j)/2 es la distancia real entre centros, así que
        w_ij = 1 / dist_centros. Con celdas uniformes de lado s esto da w_ij = 1/s,
        reproduciendo EXACTAMENTE el Laplaciano de la grilla regular (mismo orden
        Fortran) → garantía de recuperación pixel-perfect en max_refinement_depth=0.

        Estructura resultante (CSR, n_cells × n_cells):
            - Simétrica (L == L.T): cada par no ordenado aporta entradas i→j y j→i.
            - Diagonal negativa: L[i,i] = -Σ_j w_ij (self-coupling).
            - Suma de filas ≈ 0 (propiedad de operador de difusión / masa).

        El acoplamiento depende SOLO de las extensiones en el eje de contacto (no del
        área de cara compartida), igual que la ruta regular: esto mantiene la
        equivalencia pixel-perfect. El refinamiento de área es trabajo futuro.
        """
        cells = self._cells
        n = cells.shape[0]
        sizes = self._sizes_of(cells)          # (n, 3) extensiones [dx, dy, dz]

        # Tolerancia de contacto/solape relativa al tamaño de celda más pequeño.
        min_size = float(sizes.min()) if n > 0 else 1.0
        tol = 1e-9 * max(min_size, 1.0)

        rows: list = []
        cols: list = []
        data: list = []

        # (lo_col, hi_col) de cada eje en el layout de bounds [x0,x1,y0,y1,z0,z1].
        axis_cols = ((0, 1), (2, 3), (4, 5))

        # ── Broadphase por hash espacial (fix O(n^5/3) → O(n + pares)) ─────────
        # El bug previo indexaba face_map SOLO por la coordenada del plano de
        # contacto: todas las celdas con cara inferior en ese plano caían en un
        # único bucket (ny×nz celdas en una grilla regional) → loop interno
        # O(slab) por celda. Aquí se indexa ADEMÁS por las dos coordenadas
        # transversales, cuantizadas a la lattice de la celda más fina (min_size).
        # En un split octree TODAS las caras son múltiplos enteros de min_size, así
        # que el binning es exacto: dos celdas con solape transversal positivo lo
        # tienen ≥ min_size (es múltiplo de la lattice) → comparten ≥1 bin entero,
        # por lo que NINGÚN vecino real se pierde. El test preciso de solape abierto
        # (idéntico al previo) filtra los candidatos del mismo bin → equivalencia
        # pixel-perfect con la versión anterior, pero ~O(n) en grillas uniformes.
        inv_min = 1.0 / min_size
        origin = np.array(
            [cells[:, 0].min(), cells[:, 2].min(), cells[:, 4].min()],
            dtype=np.float64,
        )

        def _q(coord_col, axis_idx):
            # Cuantiza una columna de coordenadas a índices enteros de lattice.
            return np.round((cells[:, coord_col] - origin[axis_idx]) * inv_min).astype(np.int64)

        for axis, (lo, hi) in enumerate(axis_cols):
            a0, a1 = [a for a in range(3) if a != axis]   # dos ejes transversales
            a0_lo, a0_hi = a0 * 2, a0 * 2 + 1
            a1_lo, a1_hi = a1 * 2, a1 * 2 + 1

            lo_plane = _q(lo, axis)        # plano de cara INFERIOR (índice entero)
            hi_plane = _q(hi, axis)        # plano de cara SUPERIOR
            b0_lo = _q(a0_lo, a0); b0_hi = _q(a0_hi, a0)   # rango de bins en a0
            b1_lo = _q(a1_lo, a1); b1_hi = _q(a1_hi, a1)   # rango de bins en a1

            # Mapa: (plano_inferior, bin_a0, bin_a1) → celdas que cubren ese bin.
            # Cada celda se registra en TODOS los bins transversales que cubre.
            face_map: dict = {}
            for j in range(n):
                p = int(lo_plane[j])
                for bx in range(int(b0_lo[j]), int(b0_hi[j])):
                    for by in range(int(b1_lo[j]), int(b1_hi[j])):
                        face_map.setdefault((p, bx, by), []).append(j)

            # Una celda i toca a j si su cara SUPERIOR coincide con la cara INFERIOR
            # de j y hay solape abierto en los dos ejes transversales.
            for i in range(n):
                p = int(hi_plane[i])
                cand: set = set()
                for bx in range(int(b0_lo[i]), int(b0_hi[i])):
                    for by in range(int(b1_lo[i]), int(b1_hi[i])):
                        bucket = face_map.get((p, bx, by))
                        if bucket:
                            cand.update(bucket)
                if not cand:
                    continue
                for j in cand:
                    ov0 = (min(cells[i, a0_hi], cells[j, a0_hi])
                           - max(cells[i, a0_lo], cells[j, a0_lo]))
                    if ov0 <= tol:
                        continue
                    ov1 = (min(cells[i, a1_hi], cells[j, a1_hi])
                           - max(cells[i, a1_lo], cells[j, a1_lo]))
                    if ov1 <= tol:
                        continue
                    w = 2.0 / (sizes[i, axis] + sizes[j, axis])
                    rows.append(i); cols.append(j); data.append(w)
                    rows.append(j); cols.append(i); data.append(w)

        if not rows:
            # Malla de una sola celda (o degenerada): Laplaciano nulo.
            return sp.csr_matrix((n, n), dtype=np.float64)

        off_diag = sp.coo_matrix(
            (np.asarray(data, dtype=np.float64),
             (np.asarray(rows, dtype=np.int64), np.asarray(cols, dtype=np.int64))),
            shape=(n, n),
        )
        diag_data = -np.asarray(off_diag.sum(axis=1)).ravel()
        L = (off_diag + sp.diags(diag_data, 0, dtype=np.float64)).tocsr()
        return L

    @property
    def levels(self) -> np.ndarray:
        """(n_cells,) — nivel de refinamiento de cada celda (0 = base)."""
        return self._levels.copy()

    @property
    def n_cells(self) -> int:
        """Número total de celdas en la malla."""
        return int(self._cells.shape[0])

    @property
    def domain_volume(self) -> float:
        """Volumen físico total del dominio."""
        return float(
            (self.x_bounds[1] - self.x_bounds[0])
            * (self.y_bounds[1] - self.y_bounds[0])
            * (self.z_bounds[1] - self.z_bounds[0])
        )

    def __repr__(self) -> str:
        return (
            f"TreeMesh(n_cells={self.n_cells}, base={self.base_cell_size:.1f}m, "
            f"max_depth={self.max_refinement_depth}, "
            f"levels={np.unique(self._levels).tolist()})"
        )
