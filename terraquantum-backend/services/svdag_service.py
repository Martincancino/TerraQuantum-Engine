"""
FASE 5 God-Tier (5.3) — Modelo categórico comprimido: Sparse Voxel DAG (SVDAG)
===============================================================================

Estructura de compresión para el modelo geológico CATEGÓRICO (una etiqueta de
litología/clase por vóxel), análogo categórico del backbone continuo VDB de 5.1.

SVDAG (Kämpe, Sintorn & Assarsson, "High Resolution Sparse Voxel DAGs", 2013):
construye un octree sobre la grilla categórica y, de abajo hacia arriba,
DEDUPLICA subárboles idénticos → el árbol colapsa en un DAG. Las regiones
homogéneas (grandes bloques de la misma litología, aire) se reducen a UN solo
nodo compartido. Para modelos geológicos —dominados por dominios homogéneos—
la compresión es enorme.

Fuente de etiquetas categóricas (el dato YA existe hoy, sin Fase 7):
  - `PGIEngine.predict_class(m_abs)` → asignación MAP de clase por vóxel.
  - `build_categorical_from_volume(volume, ...)` → clasifica el CoRegisteredVolume
    de 5.1/5.2 por binning de cuantiles de un canal (default honesto).
  - etiquetas explícitas (array) → permite que Fase 7 (geología implícita) nutra
    el SVDAG con un modelo categórico más rico SIN cambiar esta estructura.

NOTA de honestidad: el roadmap marca 5.3 como "depende de Fase 7". Esa dependencia
es por la MEJOR fuente de etiquetas (geología implícita), no por la estructura:
el SVDAG aquí es completo y correcto, alimentado por las fuentes categóricas que
existen hoy. El render GPU del SVDAG (ray-marching) es Fase 6, NO aquí.

Reglas de diseño (estilo del motor): aditivo, aislado, opt-in, sin deps nuevas.

Autor: TerraQuantum Backend | Fase 5 God-Tier (5.3)
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

import numpy as np

logger = logging.getLogger(__name__)

# Etiqueta reservada para vóxeles vacíos / aire / sin clase.
EMPTY_LABEL = 0
# Aviso de costo: por encima de este lado de cubo el build en Python puro es lento.
_SIDE_WARN_THRESHOLD = 256


def _next_pow2(n: int) -> int:
    p = 1
    while p < n:
        p <<= 1
    return p


# ─────────────────────────────────────────────────────────────────────────────
# Estructura SVDAG
# ─────────────────────────────────────────────────────────────────────────────

@dataclass
class SVDAG:
    """
    Sparse Voxel DAG sobre una grilla categórica.

    Representación del grafo (tablas paralelas, índice = id de nodo):
      node_is_leaf : (M,) bool   — True si el nodo es una hoja (región homogénea)
      node_label   : (M,) int32  — etiqueta de la hoja (válido si is_leaf)
      node_children: (M,8) int32 — ids de los 8 hijos (válido si NO is_leaf; -1 hoja)

    Geometría:
      side   : lado del cubo octree (potencia de 2, ≥ max(nx,ny,nz))
      levels : profundidad (side == 2**levels)
      dims   : (nx, ny, nz) dimensiones ORIGINALES antes del padding a cubo pow2

    Orden de octantes en cada nivel: child = bit_x | (bit_y<<1) | (bit_z<<2).
    """

    side: int
    levels: int
    dims: tuple[int, int, int]
    root: int
    n_categories: int
    node_is_leaf: np.ndarray
    node_label: np.ndarray
    node_children: np.ndarray

    @property
    def n_nodes(self) -> int:
        return int(self.node_is_leaf.size)

    # ── Query ──────────────────────────────────────────────────────────────────
    def get_label(self, ix: int, iy: int, iz: int) -> int:
        """Etiqueta categórica del vóxel (ix,iy,iz). Fuera de dims originales → EMPTY."""
        nx, ny, nz = self.dims
        if not (0 <= ix < nx and 0 <= iy < ny and 0 <= iz < nz):
            return EMPTY_LABEL
        node = self.root
        size = self.side
        x, y, z = ix, iy, iz
        while not self.node_is_leaf[node]:
            size >>= 1
            bx = 1 if (x & size) else 0
            by = 1 if (y & size) else 0
            bz = 1 if (z & size) else 0
            octant = bx | (by << 1) | (bz << 2)
            node = int(self.node_children[node, octant])
        return int(self.node_label[node])

    def to_dense(self) -> np.ndarray:
        """Reconstruye la grilla categórica densa (nx,ny,nz) int32 desde el DAG."""
        nx, ny, nz = self.dims
        out = np.empty((nx, ny, nz), dtype=np.int32)
        for ix in range(nx):
            for iy in range(ny):
                for iz in range(nz):
                    out[ix, iy, iz] = self.get_label(ix, iy, iz)
        return out

    # ── Estadísticas de compresión ───────────────────────────────────────────
    def stats(self) -> dict:
        """Métricas de compresión: nodos del DAG vs vóxeles y vs octree denso."""
        n_voxels_cube = self.side ** 3
        # Octree denso (sin dedup): nodos = sum_{l=0..levels} 8^l = (8^(L+1)-1)/7.
        dense_octree_nodes = (8 ** (self.levels + 1) - 1) // 7
        return {
            "n_dag_nodes": self.n_nodes,
            "n_leaves": int(np.count_nonzero(self.node_is_leaf)),
            "n_internal": int(np.count_nonzero(~self.node_is_leaf)),
            "side": self.side,
            "levels": self.levels,
            "dims": self.dims,
            "n_categories": self.n_categories,
            "n_voxels_cube": int(n_voxels_cube),
            "dense_octree_nodes": int(dense_octree_nodes),
            "compression_vs_voxels": round(n_voxels_cube / max(self.n_nodes, 1), 2),
            "compression_vs_octree": round(dense_octree_nodes / max(self.n_nodes, 1), 2),
        }

    # ── Persistencia ───────────────────────────────────────────────────────────
    def to_npz(self, path: str) -> str:
        out = Path(path)
        out.parent.mkdir(parents=True, exist_ok=True)
        np.savez_compressed(
            str(out),
            side=np.int64(self.side),
            levels=np.int64(self.levels),
            dims=np.asarray(self.dims, dtype=np.int64),
            root=np.int64(self.root),
            n_categories=np.int64(self.n_categories),
            node_is_leaf=self.node_is_leaf,
            node_label=self.node_label,
            node_children=self.node_children,
        )
        final = str(out) if out.suffix == ".npz" else str(out) + ".npz"
        st = self.stats()
        logger.info(
            "[FASE 5.3] SVDAG .npz | path=%s | dims=%s | nodos=%d | compresión vs vóxeles=%.1fx",
            final, self.dims, self.n_nodes, st["compression_vs_voxels"],
        )
        return final

    @classmethod
    def from_npz(cls, path: str) -> "SVDAG":
        with np.load(path) as z:
            return cls(
                side=int(z["side"]),
                levels=int(z["levels"]),
                dims=tuple(int(v) for v in z["dims"]),
                root=int(z["root"]),
                n_categories=int(z["n_categories"]),
                node_is_leaf=z["node_is_leaf"].astype(bool),
                node_label=z["node_label"].astype(np.int32),
                node_children=z["node_children"].astype(np.int32),
            )


# ─────────────────────────────────────────────────────────────────────────────
# Builder del SVDAG desde una grilla categórica
# ─────────────────────────────────────────────────────────────────────────────

def build_svdag_from_labels(label_grid: np.ndarray) -> SVDAG:
    """
    Construye un :class:`SVDAG` desde una grilla categórica 3D (nx,ny,nz) de enteros.

    EMPTY_LABEL (0) = vacío/aire. La grilla se padea con EMPTY a un cubo pow2;
    cada subárbol homogéneo (incluido todo el padding) colapsa a un nodo compartido.
    """
    label_grid = np.asarray(label_grid)
    if label_grid.ndim != 3:
        raise ValueError(f"[FASE 5.3] label_grid debe ser 3D, recibido ndim={label_grid.ndim}.")
    if not np.issubdtype(label_grid.dtype, np.integer):
        raise ValueError("[FASE 5.3] label_grid debe ser entero (categórico).")

    nx, ny, nz = label_grid.shape
    side = _next_pow2(max(nx, ny, nz, 1))
    levels = int(side).bit_length() - 1  # side == 2**levels
    if side > _SIDE_WARN_THRESHOLD:
        logger.warning(
            "[FASE 5.3] lado de cubo %d > %d: el build SVDAG en Python puro será lento "
            "(el render/HPC del DAG es Fase 6).", side, _SIDE_WARN_THRESHOLD,
        )

    # Padear a cubo pow2 con EMPTY en las caras altas (las coords originales no cambian).
    padded = np.full((side, side, side), EMPTY_LABEL, dtype=np.int64)
    padded[:nx, :ny, :nz] = label_grid.astype(np.int64)

    # Tablas de nodos (crecen dinámicamente) + dedup por contenido canónico.
    nodes_is_leaf: list[bool] = []
    nodes_label: list[int] = []
    nodes_children: list[tuple] = []
    leaf_cache: dict[int, int] = {}          # label → node id (hoja compartida)
    internal_cache: dict[tuple, int] = {}     # (c0..c7) → node id (nodo interno dedup)

    def _leaf(label: int) -> int:
        nid = leaf_cache.get(label)
        if nid is None:
            nid = len(nodes_is_leaf)
            nodes_is_leaf.append(True)
            nodes_label.append(int(label))
            nodes_children.append((-1,) * 8)
            leaf_cache[label] = nid
        return nid

    def _internal(children: tuple) -> int:
        nid = internal_cache.get(children)
        if nid is None:
            nid = len(nodes_is_leaf)
            nodes_is_leaf.append(False)
            nodes_label.append(EMPTY_LABEL)
            nodes_children.append(children)
            internal_cache[children] = nid
        return nid

    def build(x0: int, y0: int, z0: int, size: int) -> int:
        sub = padded[x0:x0 + size, y0:y0 + size, z0:z0 + size]
        first = int(sub.flat[0])
        # Colapso de región homogénea (clave de la compresión SVDAG).
        if size == 1 or bool(np.all(sub == first)):
            return _leaf(first)
        h = size >> 1
        # Orden de octantes: child = bit_x | bit_y<<1 | bit_z<<2.
        children = (
            build(x0,     y0,     z0,     h),  # 000
            build(x0 + h, y0,     z0,     h),  # 100
            build(x0,     y0 + h, z0,     h),  # 010
            build(x0 + h, y0 + h, z0,     h),  # 110
            build(x0,     y0,     z0 + h, h),  # 001
            build(x0 + h, y0,     z0 + h, h),  # 101
            build(x0,     y0 + h, z0 + h, h),  # 011
            build(x0 + h, y0 + h, z0 + h, h),  # 111
        )
        # NO se colapsa "8 hijos idénticos → hijo": eso solo es válido para HOJAS
        # (valor homogéneo), y ese caso ya lo capturó np.all(sub==first) arriba. Para
        # nodos INTERNOS idénticos (p.ej. patrón repetido tipo checkerboard) colapsar
        # corromperia el direccionamiento (un subárbol de tamaño h representaría 2h).
        # El compartir subárboles idénticos lo da el dedup de internal_cache (DAG),
        # manteniendo el nodo padre correcto.
        return _internal(children)

    root = build(0, 0, 0, side)

    n_categories = int(len({int(v) for v in np.unique(label_grid) if int(v) != EMPTY_LABEL}))
    dag = SVDAG(
        side=side, levels=levels, dims=(nx, ny, nz), root=root,
        n_categories=n_categories,
        node_is_leaf=np.asarray(nodes_is_leaf, dtype=bool),
        node_label=np.asarray(nodes_label, dtype=np.int32),
        node_children=np.asarray(nodes_children, dtype=np.int32),
    )
    st = dag.stats()
    logger.info(
        "[FASE 5.3] SVDAG construido | dims=%dx%dx%d → cubo %d³ | categorías=%d | "
        "nodos DAG=%d (hojas=%d, internos=%d) | compresión vs vóxeles=%.1fx vs octree=%.1fx",
        nx, ny, nz, side, n_categories, dag.n_nodes, st["n_leaves"], st["n_internal"],
        st["compression_vs_voxels"], st["compression_vs_octree"],
    )
    return dag


# ─────────────────────────────────────────────────────────────────────────────
# Fuente de etiquetas: clasificación del volumen co-registrado (5.1/5.2)
# ─────────────────────────────────────────────────────────────────────────────

def build_categorical_from_volume(
    volume,
    channel: str = "density",
    n_classes: int = 4,
    thresholds: Optional[list[float]] = None,
) -> tuple[np.ndarray, dict]:
    """
    Clasifica un :class:`CoRegisteredVolume` (de volumetric_service) en una grilla
    categórica por binning de un canal. Vóxeles inactivos/NaN → EMPTY_LABEL (0);
    los activos se asignan a las clases 1..K.

    classifier honesto y simple: cuantiles del canal (igual frecuencia). NO pretende
    ser geología — es una segmentación por magnitud para alimentar el SVDAG. La
    geología real es Fase 7 (que puede pasar `thresholds` o etiquetas explícitas).

    Retorna (label_grid (nx,ny,nz) int32, meta dict).
    """
    if channel not in volume.channels:
        raise ValueError(
            f"[FASE 5.3] canal '{channel}' ausente en el volumen. Disponibles: {volume.channel_names}"
        )
    nx, ny, nz = volume.dims
    dense = volume.dense(channel)  # (nx,ny,nz) F-order, NaN en inactivos
    flat = dense.reshape(-1, order="F")
    active = np.isfinite(flat)
    vals = flat[active]

    labels = np.zeros(flat.shape[0], dtype=np.int32)  # EMPTY por defecto
    if vals.size == 0:
        meta = {"channel": channel, "n_classes": 0, "edges": [], "note": "sin vóxeles activos"}
        return labels.reshape((nx, ny, nz), order="F"), meta

    if thresholds is not None:
        edges = np.asarray(sorted(thresholds), dtype=np.float64)
    else:
        # Cuantiles internos (n_classes-1 cortes) → clases de igual frecuencia.
        qs = np.linspace(0.0, 1.0, n_classes + 1)[1:-1]
        edges = np.quantile(vals, qs) if qs.size > 0 else np.array([], dtype=np.float64)
        edges = np.unique(edges)  # colapsa cortes degenerados (canal casi constante)

    # np.digitize → 0..len(edges); +1 para reservar 0 = EMPTY.
    cls = np.digitize(vals, edges).astype(np.int32) + 1
    labels[active] = cls

    meta = {
        "channel": channel,
        "n_classes": int(len(edges) + 1),
        "edges": [round(float(e), 6) for e in edges],
        "method": "quantile_binning" if thresholds is None else "explicit_thresholds",
        "note": (
            "Segmentación por magnitud del canal (NO geología). Clase 0 = inactivo/aire. "
            "Fuente categórica honesta para el SVDAG; la geología real es Fase 7."
        ),
    }
    return labels.reshape((nx, ny, nz), order="F"), meta


# ─────────────────────────────────────────────────────────────────────────────
# Pipeline de alto nivel
# ─────────────────────────────────────────────────────────────────────────────

def export_categorical_svdag(
    output_dir: str,
    run_prefix: str,
    volume=None,
    label_grid: Optional[np.ndarray] = None,
    channel: str = "density",
    n_classes: int = 4,
) -> dict:
    """
    Construye y serializa un SVDAG categórico a .npz.

    Fuente de etiquetas (en orden de prioridad):
      1. `label_grid` explícito (p.ej. PGIEngine.predict_class reshaped, o Fase 7).
      2. clasificación del `volume` co-registrado por binning del `channel`.

    Retorna dict con stats de compresión + ruta del .npz.
    """
    meta: dict = {}
    if label_grid is not None:
        grid = np.asarray(label_grid)
    elif volume is not None:
        grid, meta = build_categorical_from_volume(volume, channel=channel, n_classes=n_classes)
    else:
        raise ValueError("[FASE 5.3] se requiere label_grid o volume.")

    dag = build_svdag_from_labels(grid)
    npz_path = dag.to_npz(str(Path(output_dir) / (run_prefix + "_svdag.npz")))

    info = dag.stats()
    info["npz_path"] = npz_path
    info["categorization"] = meta
    return info
