"""
FASE 5 God-Tier — Estructuras Volumétricas (backbone co-registrado)
====================================================================

Co-registra los block models de inversión (gravimetría / magnetometría) en UNA
sola grilla volumétrica ESPARSA compartida, con canales co-registrados:

    densidad · contraste · susceptibilidad · incertidumbre (posterior_std) · score

La esencia de OpenVDB / NanoVDB es el almacenamiento ESPARSO de vóxeles activos
en un dominio co-registrado con múltiples canales de atributos. Este módulo
entrega esa SUSTANCIA con NumPy (siempre disponible) y ofrece export `.vdb` real
GATEADO tras ``import pyopenvdb`` — el MISMO patrón que ``pyevtk`` en
``export_service.py``: si la binding no está instalada, loguea un warning y
retorna ``None`` (non-fatal). Así, cuando el usuario instale pyopenvdb el módulo
emite VDB multi-grid sin tocar el resto del código.

Reglas de diseño (estilo del motor):
  - Aditivo y aislado: NO modifica ningún flujo de inversión existente.
  - Opt-in: solo se ejecuta si alguien lo invoca explícitamente.
  - Co-registración estricta: ambas modalidades deben compartir el MISMO retículo
    (block_size + lattice de índices ix/iy/iz). Si no, ValueError honesto.
  - Sin merge lossy: cuando ambas modalidades aportan el mismo nombre de canal,
    se sufija por modalidad (p.ej. posterior_std_density vs posterior_std_susc).

NO cubierto aquí (Fase 5 completa, fuera de este slice):
  - SVDAG para modelo categórico → depende de Fase 7 (geología implícita).
  - Cableado automático en geophysics_service (Fase 5.2).

Autor: TerraQuantum Backend | Fase 5 God-Tier (5.1)
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

import numpy as np

logger = logging.getLogger(__name__)

# Tolerancia relativa para considerar dos espaciados de grilla "el mismo retículo".
_SPACING_RTOL = 1e-3
# Valor de relleno para canales en vóxeles donde la modalidad no aportó dato.
_FILL = np.float64(np.nan)


# ─────────────────────────────────────────────────────────────────────────────
# Lectura de columnas canónicas desde los parquets del block model (v3/v4)
# ─────────────────────────────────────────────────────────────────────────────

# Nombre de salida del canal  →  lista de columnas candidatas (prioridad descendente)
_CHANNEL_COLUMNS: dict[str, list[str]] = {
    "density":          ["density_t_m3", "density"],
    "density_contrast": ["density_contrast_t_m3", "density_contrast"],
    "susceptibility":   ["susceptibility_si"],
    "posterior_std":    ["posterior_std"],
    "target_score":     ["relative_target_score", "probability"],
    "doi_index":        ["doi_index", "doi_raw"],
    "sensitivity":      ["sensitivity_proxy"],
}

_X_COLUMNS = ["x_m", "x", "x_c"]
_Y_COLUMNS = ["y_m", "y", "y_c"]
_Z_COLUMNS = ["z_m", "z", "z_c"]


def _first_present(columns, candidates: list[str]) -> Optional[str]:
    for c in candidates:
        if c in columns:
            return c
    return None


def _read_parquet_source(path: str) -> dict:
    """
    Lee un parquet de block model y devuelve un dict con índices, coords y los
    canales presentes. Usa polars si está disponible, si no pandas.
    """
    cols_obj = None
    data: dict = {}

    try:
        import polars as pl
        df = pl.read_parquet(path)
        columns = set(df.columns)
        cols_obj = columns

        def col(name: str) -> np.ndarray:
            return df.get_column(name).to_numpy()

    except Exception:
        import pandas as pd
        df = pd.read_parquet(path)
        columns = set(df.columns)
        cols_obj = columns

        def col(name: str) -> np.ndarray:
            return df[name].to_numpy()

    for idx_name in ("ix", "iy", "iz"):
        if idx_name not in cols_obj:
            raise ValueError(
                f"[FASE 5] Parquet '{path}' no tiene la columna de índice '{idx_name}'. "
                "La co-registración volumétrica requiere ix/iy/iz."
            )

    data["ix"] = np.asarray(col("ix"), dtype=np.int64)
    data["iy"] = np.asarray(col("iy"), dtype=np.int64)
    data["iz"] = np.asarray(col("iz"), dtype=np.int64)

    xname = _first_present(cols_obj, _X_COLUMNS)
    yname = _first_present(cols_obj, _Y_COLUMNS)
    zname = _first_present(cols_obj, _Z_COLUMNS)
    if not (xname and yname and zname):
        raise ValueError(
            f"[FASE 5] Parquet '{path}' no tiene coordenadas de centro (x_m/y_m/z_m)."
        )
    data["x"] = np.asarray(col(xname), dtype=np.float64)
    data["y"] = np.asarray(col(yname), dtype=np.float64)
    data["z"] = np.asarray(col(zname), dtype=np.float64)

    channels: dict[str, np.ndarray] = {}
    for out_name, candidates in _CHANNEL_COLUMNS.items():
        src = _first_present(cols_obj, candidates)
        if src is not None:
            channels[out_name] = np.asarray(col(src), dtype=np.float64)
    data["channels"] = channels

    # is_active explícito si existe; si no, se infiere por modalidad más abajo.
    if "is_active" in cols_obj:
        data["is_active"] = np.asarray(col("is_active"), dtype=bool)
    else:
        data["is_active"] = None

    return data


def _infer_spacing(centers: np.ndarray, indices: np.ndarray) -> float:
    """
    Estima el tamaño de celda en un eje desde centros y sus índices enteros.

    Robusto a índices no contiguos: spacing = mediana( Δcenter / Δindex ) sobre
    pares con Δindex != 0, ordenados por índice.
    """
    order = np.argsort(indices, kind="stable")
    ci = centers[order]
    ii = indices[order].astype(np.float64)
    d_idx = np.diff(ii)
    d_ctr = np.diff(ci)
    mask = np.abs(d_idx) > 0
    if not np.any(mask):
        return 1.0  # eje degenerado (una sola capa): spacing nominal
    ratios = d_ctr[mask] / d_idx[mask]
    ratios = ratios[np.isfinite(ratios) & (ratios > 0)]
    if ratios.size == 0:
        return 1.0
    return float(np.median(ratios))


# ─────────────────────────────────────────────────────────────────────────────
# Estructura de datos: volumen esparso co-registrado
# ─────────────────────────────────────────────────────────────────────────────

@dataclass
class CoRegisteredVolume:
    """
    Volumen esparso co-registrado: una sola geometría de grilla + N canales,
    todos alineados a un único arreglo de índices de vóxeles activos.

    Geometría
    ─────────
    dims          : (nx, ny, nz) número de celdas por eje (lattice normalizado a 0)
    spacing       : (dx, dy, dz) tamaño de celda en metros
    world_origin  : (x0, y0, z0) centro del vóxel (0,0,0) en coords mundo
    index_origin  : (ix0, iy0, iz0) índice original mínimo (lo que se restó al lattice)

    Datos
    ─────
    active_index  : (n_active,) int64 — índices planos F-order en [0, nx*ny*nz)
    channels      : dict[str, (n_active,) float64] — un valor por vóxel activo
    """

    dims: tuple[int, int, int]
    spacing: tuple[float, float, float]
    world_origin: tuple[float, float, float]
    index_origin: tuple[int, int, int]
    active_index: np.ndarray
    channels: dict[str, np.ndarray] = field(default_factory=dict)

    # ── Propiedades derivadas ────────────────────────────────────────────────
    @property
    def n_active(self) -> int:
        return int(self.active_index.size)

    @property
    def n_total(self) -> int:
        nx, ny, nz = self.dims
        return int(nx) * int(ny) * int(nz)

    @property
    def channel_names(self) -> list[str]:
        return sorted(self.channels.keys())

    @property
    def fill_ratio(self) -> float:
        """Fracción de vóxeles activos (densidad de ocupación del dominio)."""
        tot = self.n_total
        return float(self.n_active / tot) if tot > 0 else 0.0

    # ── Acceso denso ───────────────────────────────────────────────────────────
    def dense(self, channel: str, fill: float = float("nan")) -> np.ndarray:
        """
        Reconstruye un arreglo denso (nx, ny, nz) F-order para un canal.
        Vóxeles inactivos = ``fill`` (NaN por defecto).
        """
        if channel not in self.channels:
            raise KeyError(f"[FASE 5] Canal '{channel}' no existe. Disponibles: {self.channel_names}")
        nx, ny, nz = self.dims
        flat = np.full(nx * ny * nz, fill, dtype=np.float64)
        flat[self.active_index] = self.channels[channel]
        return flat.reshape((nx, ny, nz), order="F")

    def voxel_world_centers(self) -> np.ndarray:
        """
        Coordenadas mundo (n_active, 3) del centro de cada vóxel activo.
        Deriva (ix,iy,iz) del índice plano F-order y aplica origin + spacing.
        """
        nx, ny, nz = self.dims
        lin = self.active_index
        ixn = lin % nx
        iyn = (lin // nx) % ny
        izn = lin // (nx * ny)
        dx, dy, dz = self.spacing
        x0, y0, z0 = self.world_origin
        xs = x0 + ixn * dx
        ys = y0 + iyn * dy
        zs = z0 + izn * dz
        return np.column_stack([xs, ys, zs]).astype(np.float64)

    # ── Persistencia NumPy (backbone siempre disponible) ───────────────────────
    def to_npz(self, path: str) -> str:
        """Serializa el volumen co-registrado a un .npz comprimido."""
        out = Path(path)
        out.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "dims": np.asarray(self.dims, dtype=np.int64),
            "spacing": np.asarray(self.spacing, dtype=np.float64),
            "world_origin": np.asarray(self.world_origin, dtype=np.float64),
            "index_origin": np.asarray(self.index_origin, dtype=np.int64),
            "active_index": self.active_index.astype(np.int64),
            "__channel_names__": np.asarray(self.channel_names, dtype=object),
        }
        for name in self.channel_names:
            payload[f"ch__{name}"] = self.channels[name].astype(np.float64)
        np.savez_compressed(str(out), **payload)
        final = str(out) if out.suffix == ".npz" else str(out) + ".npz"
        logger.info(
            "[FASE 5] Volumen co-registrado .npz | path=%s | dims=%s | activos=%d/%d | canales=%s",
            final, self.dims, self.n_active, self.n_total, self.channel_names,
        )
        return final

    @classmethod
    def from_npz(cls, path: str) -> "CoRegisteredVolume":
        with np.load(path, allow_pickle=True) as z:
            dims = tuple(int(v) for v in z["dims"])
            spacing = tuple(float(v) for v in z["spacing"])
            world_origin = tuple(float(v) for v in z["world_origin"])
            index_origin = tuple(int(v) for v in z["index_origin"])
            active_index = z["active_index"].astype(np.int64)
            names = [str(n) for n in z["__channel_names__"]]
            channels = {n: z[f"ch__{n}"].astype(np.float64) for n in names}
        return cls(
            dims=dims, spacing=spacing, world_origin=world_origin,
            index_origin=index_origin, active_index=active_index, channels=channels,
        )


# ─────────────────────────────────────────────────────────────────────────────
# Builder: co-registra uno o ambos parquets en un solo volumen
# ─────────────────────────────────────────────────────────────────────────────

def build_coregistered_volume_from_parquets(
    gravity_path: Optional[str] = None,
    magnetic_path: Optional[str] = None,
) -> CoRegisteredVolume:
    """
    Construye un :class:`CoRegisteredVolume` a partir de uno o ambos block models.

    - Si ambos están presentes, deben compartir el MISMO retículo (block_size +
      lattice ix/iy/iz). Si difieren, se levanta ValueError (co-registración honesta).
    - Vóxel activo = activo en AL MENOS una modalidad.
    - Canales de gravimetría: density, density_contrast, posterior_std_density,
      target_score_gravity, doi_index, sensitivity_gravity.
    - Canales de magnetometría: susceptibility, posterior_std_susc,
      target_score_magnetic, sensitivity_magnetic.
    """
    if not gravity_path and not magnetic_path:
        raise ValueError("[FASE 5] Se requiere al menos un parquet (gravity_path o magnetic_path).")

    sources: list[tuple[str, dict]] = []
    if gravity_path:
        sources.append(("gravity", _read_parquet_source(gravity_path)))
    if magnetic_path:
        sources.append(("magnetic", _read_parquet_source(magnetic_path)))

    # ── 1. Geometría global: bounds de índices + spacing por eje ──────────────
    ix_all = np.concatenate([s["ix"] for _, s in sources])
    iy_all = np.concatenate([s["iy"] for _, s in sources])
    iz_all = np.concatenate([s["iz"] for _, s in sources])

    ix0, iy0, iz0 = int(ix_all.min()), int(iy_all.min()), int(iz_all.min())
    nx = int(ix_all.max()) - ix0 + 1
    ny = int(iy_all.max()) - iy0 + 1
    nz = int(iz_all.max()) - iz0 + 1

    # Spacing por fuente, luego verificación de co-registración.
    spacings: list[tuple[float, float, float]] = []
    for _, s in sources:
        dx = _infer_spacing(s["x"], s["ix"])
        dy = _infer_spacing(s["y"], s["iy"])
        dz = _infer_spacing(s["z"], s["iz"])
        spacings.append((dx, dy, dz))

    dx, dy, dz = spacings[0]
    for (label, _), (sdx, sdy, sdz) in zip(sources, spacings):
        if not (
            np.isclose(sdx, dx, rtol=_SPACING_RTOL)
            and np.isclose(sdy, dy, rtol=_SPACING_RTOL)
            and np.isclose(sdz, dz, rtol=_SPACING_RTOL)
        ):
            raise ValueError(
                f"[FASE 5] Co-registración imposible: la modalidad '{label}' usa "
                f"spacing ({sdx:.3f},{sdy:.3f},{sdz:.3f}) ≠ ({dx:.3f},{dy:.3f},{dz:.3f}). "
                "Ambas modalidades deben compartir el mismo retículo."
            )

    # World origin = centro del vóxel (ix0,iy0,iz0). Se toma de la primera fuente
    # que contenga ese índice; si ninguna, se extrapola desde el centro mínimo.
    def _world_origin_axis(centers, indices, idx0, spacing) -> float:
        hit = np.where(indices == idx0)[0]
        if hit.size > 0:
            return float(centers[hit[0]])
        return float(centers.min()) - (float(indices.min()) - idx0) * spacing

    s0 = sources[0][1]
    x0w = _world_origin_axis(s0["x"], s0["ix"], ix0, dx)
    y0w = _world_origin_axis(s0["y"], s0["iy"], iy0, dy)
    z0w = _world_origin_axis(s0["z"], s0["iz"], iz0, dz)

    # ── 2. Índice plano F-order normalizado por fuente ────────────────────────
    def _flat(s: dict) -> np.ndarray:
        lix = s["ix"] - ix0
        liy = s["iy"] - iy0
        liz = s["iz"] - iz0
        return (lix + nx * (liy + ny * liz)).astype(np.int64)

    # ── 3. Máscara de actividad por fuente ────────────────────────────────────
    def _active_mask(s: dict) -> np.ndarray:
        if s["is_active"] is not None:
            return s["is_active"]
        # Inferir: activo si algún canal primario es finito.
        ch = s["channels"]
        primary = ch.get("density")
        if primary is None:
            primary = ch.get("susceptibility")
        if primary is None:
            return np.ones(len(s["ix"]), dtype=bool)
        return np.isfinite(primary)

    # ── 4. Unión de vóxeles activos sobre el lattice global ───────────────────
    active_flats = []
    per_source = []
    for label, s in sources:
        flat = _flat(s)
        amask = _active_mask(s)
        active_flats.append(flat[amask])
        per_source.append((label, s, flat, amask))
    union = np.unique(np.concatenate(active_flats)) if active_flats else np.array([], dtype=np.int64)

    # ── 5. Scatter de canales sobre el índice unión ───────────────────────────
    # Mapa flat-global → posición en `union` (búsqueda binaria).
    def _to_union_pos(flats: np.ndarray) -> np.ndarray:
        return np.searchsorted(union, flats)

    # Sufijos por modalidad para canales que ambas aportan.
    _channel_out_name = {
        ("gravity", "density"): "density",
        ("gravity", "density_contrast"): "density_contrast",
        ("gravity", "posterior_std"): "posterior_std_density",
        ("gravity", "target_score"): "target_score_gravity",
        ("gravity", "doi_index"): "doi_index",
        ("gravity", "sensitivity"): "sensitivity_gravity",
        ("magnetic", "susceptibility"): "susceptibility",
        ("magnetic", "posterior_std"): "posterior_std_susc",
        ("magnetic", "target_score"): "target_score_magnetic",
        ("magnetic", "sensitivity"): "sensitivity_magnetic",
        # density/contrast/doi en magnético se ignoran (suelen ser placeholders).
    }

    channels: dict[str, np.ndarray] = {}
    for label, s, flat, amask in per_source:
        pos = _to_union_pos(flat)
        # Solo escribir donde: (a) el vóxel está en la unión Y (b) la modalidad lo
        # marca ACTIVO. Un vóxel activo en otra modalidad pero inactivo en ésta NO
        # recibe el placeholder de aire (p.ej. susc=0.0): queda NaN (sin dato real).
        valid = (
            (pos >= 0) & (pos < union.size)
            & (union[np.clip(pos, 0, union.size - 1)] == flat)
            & amask
        )
        for ch_in, values in s["channels"].items():
            out_name = _channel_out_name.get((label, ch_in))
            if out_name is None:
                continue
            if out_name not in channels:
                channels[out_name] = np.full(union.size, _FILL, dtype=np.float64)
            channels[out_name][pos[valid]] = values[valid]

    vol = CoRegisteredVolume(
        dims=(nx, ny, nz),
        spacing=(dx, dy, dz),
        world_origin=(x0w, y0w, z0w),
        index_origin=(ix0, iy0, iz0),
        active_index=union,
        channels=channels,
    )
    logger.info(
        "[FASE 5] Volumen co-registrado | fuentes=%s | dims=%dx%dx%d | spacing=(%.2f,%.2f,%.2f) "
        "| activos=%d/%d (%.2f%%) | canales=%s",
        [lbl for lbl, _ in sources], nx, ny, nz, dx, dy, dz,
        vol.n_active, vol.n_total, 100.0 * vol.fill_ratio, vol.channel_names,
    )
    return vol


# ─────────────────────────────────────────────────────────────────────────────
# Export OpenVDB — GATEADO tras `import pyopenvdb` (mismo patrón que pyevtk)
# ─────────────────────────────────────────────────────────────────────────────

def export_volume_to_vdb(volume: CoRegisteredVolume, path: str) -> Optional[str]:
    """
    Exporta el volumen co-registrado a un archivo OpenVDB multi-grid (.vdb),
    un FloatGrid por canal con transform lineal = spacing del retículo.

    GATEADO: si pyopenvdb no está instalado, loguea un warning y retorna None
    (non-fatal) — exactamente el patrón de export_block_model_to_vtr con pyevtk.
    El backbone real es to_npz(); VDB es el bonus de interoperabilidad GPU/DCC.

    Limitación honesta: pyopenvdb solo soporta voxelSize escalar uniforme en su
    transform lineal por defecto. Si el retículo es anisótropo (dx≠dy≠dz) se usa
    dx como voxelSize y se loguea la advertencia (las coords de índice se preservan).
    """
    try:
        import pyopenvdb as vdb  # type: ignore
    except ImportError:
        logger.warning(
            "[FASE 5] pyopenvdb no instalado — export VDB omitido (non-fatal). "
            "El backbone .npz sí se generó. Para VDB: instalar openvdb con bindings Python."
        )
        return None

    nx, ny, nz = volume.dims
    dx, dy, dz = volume.spacing
    if not (np.isclose(dx, dy) and np.isclose(dy, dz)):
        logger.warning(
            "[FASE 5] Retículo anisótropo (%.3f,%.3f,%.3f): VDB usa voxelSize=%.3f uniforme.",
            dx, dy, dz, dx,
        )

    out = Path(path)
    out.parent.mkdir(parents=True, exist_ok=True)

    # Índices normalizados (ix,iy,iz) de cada vóxel activo, en C-order para el accessor.
    lin = volume.active_index
    ixn = (lin % nx).astype(np.int32)
    iyn = ((lin // nx) % ny).astype(np.int32)
    izn = (lin // (nx * ny)).astype(np.int32)

    transform = vdb.createLinearTransform(voxelSize=float(dx))
    grids = []
    for name in volume.channel_names:
        grid = vdb.FloatGrid()
        grid.name = name
        grid.transform = transform
        acc = grid.getAccessor()
        vals = volume.channels[name]
        for k in range(lin.size):
            v = float(vals[k])
            if np.isfinite(v):
                acc.setValueOn((int(ixn[k]), int(iyn[k]), int(izn[k])), v)
        grids.append(grid)

    vdb.write(str(out), grids=grids)
    logger.info(
        "[FASE 5] VDB multi-grid escrito | path=%s | grids=%d | activos=%d",
        str(out), len(grids), volume.n_active,
    )
    return str(out)


# ─────────────────────────────────────────────────────────────────────────────
# Pipeline de alto nivel
# ─────────────────────────────────────────────────────────────────────────────

def export_coregistered_volume(
    output_dir: str,
    run_prefix: str,
    gravity_path: Optional[str] = None,
    magnetic_path: Optional[str] = None,
    write_vdb: bool = True,
    write_svdag: bool = False,
    svdag_channel: str = "density",
    svdag_n_classes: int = 4,
) -> dict:
    """
    Pipeline completo: construye el volumen co-registrado, lo persiste a .npz
    (siempre) y opcionalmente a .vdb (si pyopenvdb está disponible) y/o a un
    modelo categórico comprimido SVDAG (.npz) derivado por binning de un canal.

    Retorna dict {"npz_path", "vdb_path", "dims", "n_active", "channels", "svdag"}.
    npz_path siempre presente; vdb_path = None si pyopenvdb falta o write_vdb=False;
    svdag = None si write_svdag=False (o stats del DAG + ruta si True).
    """
    vol = build_coregistered_volume_from_parquets(
        gravity_path=gravity_path, magnetic_path=magnetic_path,
    )
    base = str(Path(output_dir) / run_prefix)
    npz_path = vol.to_npz(base + ".npz")
    vdb_path = export_volume_to_vdb(vol, base + ".vdb") if write_vdb else None

    # ── Fase 5.3: modelo categórico comprimido (SVDAG) desde el MISMO volumen ──
    svdag_info = None
    if write_svdag:
        try:
            from services.svdag_service import export_categorical_svdag
            svdag_info = export_categorical_svdag(
                output_dir=output_dir, run_prefix=run_prefix,
                volume=vol, channel=svdag_channel, n_classes=svdag_n_classes,
            )
        except Exception as _svdag_exc:
            logger.warning("[FASE 5.3] SVDAG export non-fatal: %s", _svdag_exc)

    return {
        "npz_path": npz_path,
        "vdb_path": vdb_path,
        "dims": vol.dims,
        "spacing": vol.spacing,
        "n_active": vol.n_active,
        "n_total": vol.n_total,
        "fill_ratio": vol.fill_ratio,
        "channels": vol.channel_names,
        "svdag": svdag_info,
    }
