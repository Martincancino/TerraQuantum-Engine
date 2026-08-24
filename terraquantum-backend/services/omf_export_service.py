"""
FASE 12 — Open Mining Format (OMF v1): dejar de ser una isla.
=============================================================

Exporta una corrida de TerraQuantum a un fichero `.omf` que abre en el software
con el que un consultor entrega a una minera (Leapfrog, Vulcan, Micromine,
Deswik) y en los lectores abiertos (`omf`, `omfvista`, `omf-rust`).

Contenido del fichero, todo leído de artefactos YA persistidos (Regla de Oro:
aquí NO se ejecuta física nueva; la única excepción declarada son las
isosuperficies, que `isosurface_service` calcula al vuelo por diseño):

  · `VolumeElement`  — el block model, malla regular, con los atributos curados.
  · `PointSetElement`— estaciones de campo con observado/calculado/residual.
  · `LineSetElement` — trazas de sondaje (intervalos verticales).
  · `SurfaceElement` — isosuperficies de contraste, una por nivel.

─────────────────────────────────────────────────────────────────────────────
LAS TRES DECISIONES QUE HACEN QUE EL FICHERO ABRA BIEN (medidas, no supuestas)
─────────────────────────────────────────────────────────────────────────────

1) **PERMUTACIÓN DE EJES.** El modelo interno de TerraQuantum NO es (E, N, Z):
   es `x_m`=Este, `y_m`=PROFUNDIDAD positiva hacia ABAJO, `z_m`=Norte, aplanado
   en orden Fortran (`idx = ix + nx*iy + nx*ny*iz`). Está declarado en
   `services/gravity_import_service.py` (permutación del export UBC) y se
   verificó en disco: en una corrida con `ny=10`, `depth=1000`, `block_size=100`,
   `y_m` llega a 950 y `x_m`/`z_m` a 1950 con `nx=nz=20`.
   OMF se escribe en (u=Este, v=Norte, w=ARRIBA) → `_permute_tq_grid_to_omf`.

2) **ORDEN DE LAS CELDAS.** La especificación de GMG para el modelo de bloques
   dice literalmente «Ordering increases U first, then V, then W» — orden
   Fortran, el mismo que ya usa TerraQuantum. Se sigue la especificación.
   ⚠️ CAVEAT MEDIDO: `omfvista` (el lector de PyVista) hace
   `np.reshape(arr, (nu,nv,nw))` en orden **C** y luego `.flatten(order="F")`,
   lo que equivale a leer W como índice rápido — es decir, TRANSPONE respecto
   de la especificación. Un fichero correcto se ve transpuesto en ese lector.
   No se «corrige» escribiendo mal a propósito: manda la especificación.

3) **DÓNDE VIVEN LAS COORDENADAS ABSOLUTAS.** Medido leyendo los conversores de
   `omfvista`: para `VolumeGridGeometry` SÍ se aplica `geometry.origin`, pero
   para PointSet / LineSet / Surface triangulada `geometry.origin` se IGNORA
   (sólo se suma el origen del *proyecto*). Por eso aquí:
     · el volumen lleva el desplazamiento absoluto en `geometry.origin`, y
     · puntos, líneas y superficies lo llevan HORNEADO en los vértices,
     · y `Project.origin` se deja en (0,0,0).
   Así los cuatro elementos caen en el mismo sitio con cualquiera de los dos
   criterios de lectura.

─────────────────────────────────────────────────────────────────────────────
LO QUE NO SE INVENTA
─────────────────────────────────────────────────────────────────────────────
· **Georreferencia.** Sólo se emiten coordenadas absolutas si la corrida guardó
  `coordinate_transform.absolute_origin` (easting/northing) Y el proyecto declara
  un CRS proyectado. Si no, el OMF sale en metros LOCALES con origen (0,0,0) y lo
  dice en su propia descripción. Medido: de 105 proyectos en disco, 25 tienen
  zona UTM; el resto NO puede georreferenciarse sin inventar.
· **Cota absoluta.** `vertical_datum` es `null` en el contrato de CRS del repo.
  El eje Z del OMF es PROFUNDIDAD bajo la superficie local (Z=0 en superficie),
  no altura sobre el nivel del mar. Está escrito en la descripción del fichero.
· **Atributos vacíos o duplicados.** La curación se decide MIDIENDO el parquet de
  la corrida (ver `_select_volume_attributes`), no por una lista fija de fe.

Autor: TerraQuantum Backend | Fase 12
"""
from __future__ import annotations

import base64
import json
import tempfile
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

import numpy as np

from core.config import APP_VERSION
from core.logging import get_logger
from services.block_model_store import (
    RUN_BLOCK_MODEL_FILENAME,
    clean_trace_context,
    get_project_meta_path,
    get_run_dir,
    get_run_gravity_import_metadata_path,
    get_run_inputs_path,
)

_log = get_logger(__name__)

# Versión del contenedor que escribe `omf==1.0.1` (constante de su fileio.py).
OMF_CONTAINER_VERSION = "OMF-v0.9.0"
# Versión del MAPEO TerraQuantum→OMF (qué elementos y qué atributos publica).
OMF_MAPPING_VERSION = "12.0"

DISCLAIMER = (
    "NO-JORC / NI 43-101 - EXPLORATION ONLY. Modelo geofisico preliminar; "
    "no constituye declaracion de Recursos ni Reservas Minerales."
)

# ── Curación de atributos del volumen ────────────────────────────────────────
# Columna del parquet → nombre publicado en el OMF. El orden es el de lectura.
#
# EXCLUIDAS A PROPÓSITO, con el motivo MEDIDO sobre una corrida real de 4000
# celdas (`data/projects/dbg_field/runs/7b4f65f644ee`):
#   · `grade`            — NaN en las 4000 celdas. Publicarla sería una ley falsa.
#   · `rho`, `density`   — bit a bit idénticas a `density_t_m3` (compatibilidad).
#   · `x`, `y`, `z`      — idénticas a `x_m`, `y_m`, `z_m`.
#   · `relative_target_score` — idéntica a `probability`.
#   · `doi_raw`          — idéntica a `doi_index`.
#   · `visual_score`     — magnitud de PINTADO del visor, no una cantidad física.
#   · `modeled_rock_mass_tonnes` — derivada trivial (densidad × volumen de celda).
#   · `density_zone_flag`— bandera interna de segmentación del visor.
_VOLUME_ATTRIBUTES: tuple[tuple[str, str], ...] = (
    ("density_t_m3", "Density_t_m3"),
    ("density_contrast_t_m3", "Density_Contrast_t_m3"),
    ("susceptibility_si", "Susceptibility_SI"),
    ("probability", "Probability_Target"),
    ("density_anomaly_score", "Density_Anomaly_Score"),
    ("sensitivity_proxy", "Sensitivity_Proxy"),
    ("doi_index", "DOI_Index"),
    ("posterior_std", "Posterior_Std_t_m3"),
    ("density_confidence_tier", "Density_Confidence_Tier"),
    ("is_active", "Is_Active"),
)


class OmfExportError(ValueError):
    """La corrida no se puede exportar a OMF sin inventar geometría o datos."""


@dataclass(frozen=True)
class OmfGridSpec:
    """Malla regular de la corrida, tal como la declaró `inputs.json`."""

    nx: int          # celdas al ESTE
    ny: int          # celdas en PROFUNDIDAD (hacia abajo)
    nz: int          # celdas al NORTE
    block_size: float  # arista de la celda cúbica (m): dx = dy = dz

    @property
    def n_cells(self) -> int:
        return self.nx * self.ny * self.nz

    @property
    def depth_m(self) -> float:
        return self.ny * self.block_size


@dataclass(frozen=True)
class OmfGeoref:
    """Marco espacial en el que se publica el OMF.

    `is_absolute=False` significa metros LOCALES con origen en la esquina SW del
    survey — que es el caso mayoritario medido en disco, y se declara como tal.
    """

    easting0: float
    northing0: float
    epsg: Optional[int]
    utm_zone: Optional[str]
    hemisphere: Optional[str]
    datum: Optional[str]
    confidence: Optional[str]
    is_absolute: bool
    source: str

    def describe(self) -> str:
        if not self.is_absolute:
            return (
                "Coordenadas LOCALES en metros, origen (0,0,0) en la esquina "
                f"SW del survey. Sin georreferencia absoluta (motivo: {self.source})."
            )
        zone = self.utm_zone or "?"
        return (
            f"Coordenadas ABSOLUTAS proyectadas. EPSG:{self.epsg} (UTM {zone}"
            f"{', ' + self.datum if self.datum else ''}). "
            f"Origen aplicado E={self.easting0:.2f} N={self.northing0:.2f}. "
            f"Confianza de georreferencia declarada por el proyecto: {self.confidence}."
        )


# ═════════════════════════════════════════════════════════════════════════════
# 1. Lectura de la definición espacial de la corrida
# ═════════════════════════════════════════════════════════════════════════════

def _read_json(path: Optional[Path]) -> Optional[dict[str, Any]]:
    if path is None or not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None


def load_grid_spec(project_id: str, run_id: str) -> OmfGridSpec:
    """Lee nx/ny/nz/block_size de `inputs.json`.

    Se exige que estén los cuatro. Sin ellos la malla NO es reconstruible y
    adivinarla (p. ej. el `infer_cell_size → 10.0` de `block_model_service`)
    sería publicar una geometría inventada en un entregable de cliente.
    """
    inputs = _read_json(get_run_inputs_path(project_id, run_id))
    if not inputs:
        raise OmfExportError(
            "La corrida no tiene inputs.json: la malla (nx, ny, nz, block_size) "
            "no es reconstruible y no se va a inventar."
        )
    try:
        spec = OmfGridSpec(
            nx=int(inputs["nx"]),
            ny=int(inputs["ny"]),
            nz=int(inputs["nz"]),
            block_size=float(inputs["block_size"]),
        )
    except (KeyError, TypeError, ValueError) as exc:
        raise OmfExportError(
            f"inputs.json no declara una malla completa (nx, ny, nz, block_size): {exc}"
        ) from exc

    if min(spec.nx, spec.ny, spec.nz) < 1 or spec.block_size <= 0:
        raise OmfExportError(
            f"Malla inválida en inputs.json: nx={spec.nx} ny={spec.ny} "
            f"nz={spec.nz} block_size={spec.block_size}."
        )
    return spec


def _projected_epsg(meta: dict[str, Any]) -> Optional[int]:
    """EPSG del CRS de ENTRADA si es proyectado (UTM). 4326 no lo es."""
    contract = meta.get("crs_contract") or {}
    for value in (contract.get("epsg_code"), meta.get("epsg_code")):
        try:
            code = int(value)
        except (TypeError, ValueError):
            continue
        if code != 4326:
            return code
    return None


def load_georef(project_id: str, run_id: str) -> OmfGeoref:
    """Determina si la corrida puede publicarse en coordenadas absolutas.

    Exige DOS cosas a la vez, y si falta una se cae a local declarándolo:
      · `coordinate_transform.absolute_origin` con easting/northing — el offset
        que el importador restó al pasar a coordenadas locales; y
      · un CRS proyectado en `project_meta.json` (`crs_contract.epsg_code`).

    El caso `local_equirectangular` guarda `lon0/lat0` en grados y NO tiene
    `absolute_origin`: tratarlo como metros sería un error de kilómetros.
    """
    meta = _read_json(get_project_meta_path(project_id)) or {}
    import_meta = _read_json(get_run_gravity_import_metadata_path(project_id, run_id)) or {}
    transform = import_meta.get("coordinate_transform") or {}
    origin = transform.get("absolute_origin") or {}
    contract = meta.get("crs_contract") or {}

    epsg = _projected_epsg(meta)
    easting = origin.get("easting")
    northing = origin.get("northing")
    has_origin = isinstance(easting, (int, float)) and isinstance(northing, (int, float))

    if has_origin and epsg is not None:
        return OmfGeoref(
            easting0=float(easting),
            northing0=float(northing),
            epsg=epsg,
            utm_zone=contract.get("utm_zone") or meta.get("utm_zone"),
            hemisphere=contract.get("utm_hemisphere") or meta.get("utm_hemisphere"),
            datum=contract.get("horizontal_datum") or meta.get("horizontal_datum"),
            confidence=meta.get("georef_confidence"),
            is_absolute=True,
            source=str(transform.get("method") or "absolute_origin"),
        )

    if has_origin:
        reason = "hay origen absoluto pero el proyecto no declara un CRS proyectado"
    elif epsg is not None:
        reason = "hay CRS proyectado pero la corrida no guardo el origen absoluto"
    else:
        reason = f"georef_type={meta.get('georef_type') or 'desconocido'}"

    return OmfGeoref(
        easting0=0.0,
        northing0=0.0,
        epsg=epsg,
        utm_zone=meta.get("utm_zone"),
        hemisphere=meta.get("utm_hemisphere"),
        datum=meta.get("horizontal_datum"),
        confidence=meta.get("georef_confidence"),
        is_absolute=False,
        source=reason,
    )


# ═════════════════════════════════════════════════════════════════════════════
# 2. La permutación de ejes (el corazón de la fase)
# ═════════════════════════════════════════════════════════════════════════════

def permute_tq_grid_to_omf(values: np.ndarray, spec: OmfGridSpec) -> np.ndarray:
    """(Este, profundidad↓, Norte) en Fortran → (u=Este, v=Norte, w=arriba) en Fortran.

    Es la MISMA permutación que `services/gravity_import_service.py` aplica al
    exportar UBC-GIF desde `load-package`: `transpose(0, 2, 1)` y volteo del
    último eje. Se reimplementa aquí en vez de importarla porque allí está
    embebida en medio de un handler de ~250 líneas del camino dorado, y esta
    fase no toca ese camino.
    """
    cube = np.asarray(values).reshape((spec.nx, spec.ny, spec.nz), order="F")
    east_north_depth = np.transpose(cube, (0, 2, 1))   # (Este, Norte, profundidad↓)
    east_north_up = east_north_depth[:, :, ::-1]       # profundidad↓ → altura↑
    return east_north_up.ravel(order="F")              # u rápido, luego v, luego w


def _dense_column(
    frame: Any, column: str, spec: OmfGridSpec, fill: float = np.nan
) -> np.ndarray:
    """Coloca una columna del parquet en el vector denso nx·ny·nz usando ix/iy/iz.

    No asume que las filas vengan ordenadas: usa los índices de celda, igual que
    hace el export UBC de producción.
    """
    idx = (
        frame["ix"].to_numpy()
        + spec.nx * frame["iy"].to_numpy()
        + spec.nx * spec.ny * frame["iz"].to_numpy()
    )
    raw = frame[column].to_numpy()
    dense = np.full(spec.n_cells, fill, dtype=np.float64)
    dense[idx] = raw.astype(np.float64)
    return dense


def _select_volume_attributes(frame: Any, spec: OmfGridSpec) -> list[tuple[str, np.ndarray]]:
    """Atributos publicables, decididos MIDIENDO esta corrida.

    Se descarta una columna si (a) no existe, (b) es NaN en todas las celdas
    presentes — publicarla sería un atributo vacío que en el visor del cliente
    parece un dato que no se calculó bien —, o (c) es bit a bit idéntica a otra
    ya seleccionada.
    """
    selected: list[tuple[str, np.ndarray]] = []
    for column, published in _VOLUME_ATTRIBUTES:
        if column not in frame.columns:
            continue
        dense = _dense_column(frame, column, spec)
        if not np.isfinite(dense).any():
            continue
        if any(np.array_equal(dense, prev, equal_nan=True) for _, prev in selected):
            continue
        selected.append((published, dense))
    return selected


# ═════════════════════════════════════════════════════════════════════════════
# 3. Construcción de los elementos OMF
# ═════════════════════════════════════════════════════════════════════════════

def _scalar_data(name: str, values: np.ndarray, location: str) -> Any:
    """`ScalarData` de OMF, siempre en float64.

    Dos motivos para float y no int, incluso en `Is_Active` o en el tier de
    confianza: (a) una celda ausente del parquet vale NaN, que no existe en
    entero; y (b) el serializador de `omf` sólo acepta float o int y con `bool`
    levanta `ValueError`, así que la conversión hay que hacerla igual.
    """
    import omf

    return omf.ScalarData(
        name=name, array=np.asarray(values, dtype=np.float64), location=location
    )


def build_volume_element(
    frame: Any, spec: OmfGridSpec, georef: OmfGeoref, name: str
) -> Any:
    """El block model como `VolumeElement` de malla regular, ya permutado."""
    import omf

    cell_widths = float(spec.block_size)
    geometry = omf.VolumeGridGeometry(
        # u = Este (nx celdas) · v = Norte (nz celdas) · w = arriba (ny celdas)
        tensor_u=np.full(spec.nx, cell_widths, dtype=np.float64),
        tensor_v=np.full(spec.nz, cell_widths, dtype=np.float64),
        tensor_w=np.full(spec.ny, cell_widths, dtype=np.float64),
        axis_u=[1.0, 0.0, 0.0],
        axis_v=[0.0, 1.0, 0.0],
        axis_w=[0.0, 0.0, 1.0],
        # Esquina inferior del volumen. Z=0 es la SUPERFICIE local, así que el
        # fondo del modelo está a -profundidad. Ver el aviso de datum vertical.
        origin=[georef.easting0, georef.northing0, -spec.depth_m],
    )
    data = [
        _scalar_data(published, permute_tq_grid_to_omf(dense, spec), "cells")
        for published, dense in _select_volume_attributes(frame, spec)
    ]
    if not data:
        raise OmfExportError(
            "El block model no tiene ni un atributo publicable (todas las "
            "columnas conocidas faltan o son NaN en todas las celdas)."
        )
    return omf.VolumeElement(name=name, geometry=geometry, data=data)


def build_station_pointset(run_dir: Path, georef: OmfGeoref) -> Optional[Any]:
    """Estaciones de campo con observado / calculado / residual.

    Medido: `obs_vs_calc.parquet` sólo lo escribe el persistidor GRAVIMÉTRICO,
    así que en magnética y joint este elemento no existe y se omite en silencio
    (no se fabrica un punto).
    """
    import omf
    import polars as pl

    path = run_dir / "obs_vs_calc.parquet"
    if not path.exists():
        return None
    frame = pl.read_parquet(str(path))
    needed = {"x", "y", "z", "d_obs", "d_pred", "residual"}
    if not needed.issubset(set(frame.columns)) or len(frame) == 0:
        return None

    # x=Este, y=profundidad↓, z=Norte  →  (Este, Norte, arriba), absolutas.
    vertices = np.column_stack([
        frame["x"].to_numpy().astype(np.float64) + georef.easting0,
        frame["z"].to_numpy().astype(np.float64) + georef.northing0,
        -frame["y"].to_numpy().astype(np.float64),
    ])
    data = [
        _scalar_data("Observado", frame["d_obs"].to_numpy(), "vertices"),
        _scalar_data("Calculado", frame["d_pred"].to_numpy(), "vertices"),
        _scalar_data("Residual", frame["residual"].to_numpy(), "vertices"),
    ]
    return omf.PointSetElement(
        name="Estaciones de campo",
        description=(
            "Observado vs calculado por estacion. Unidad interna del solver "
            "(m/s2), no mGal."
        ),
        geometry=omf.PointSetGeometry(vertices=vertices),
        data=data,
    )


def _borehole_segments(
    intervals: list[dict[str, Any]], georef: OmfGeoref
) -> tuple[np.ndarray, np.ndarray, list[Optional[float]], list[Optional[str]]]:
    """Cada intervalo es un segmento vertical de dos vértices.

    Los sondajes persistidos son VERTICALES por contrato (`BoreholeInterval`
    declara la limitación). No se desvía la traza ni se inventa azimut/dip.
    """
    vertices: list[list[float]] = []
    segments: list[list[int]] = []
    densities: list[Optional[float]] = []
    lithologies: list[Optional[str]] = []
    for item in intervals:
        try:
            east = float(item["x_m"]) + georef.easting0
            north = float(item["z_m"]) + georef.northing0
            top = -float(item["y_from_m"])
            bottom = -float(item["y_to_m"])
        except (KeyError, TypeError, ValueError):
            continue
        base = len(vertices)
        vertices.append([east, north, top])
        vertices.append([east, north, bottom])
        segments.append([base, base + 1])
        value = item.get("density_t_m3")
        densities.append(float(value) if isinstance(value, (int, float)) else None)
        unit = item.get("lithology")
        lithologies.append(str(unit) if isinstance(unit, str) and unit else None)
    return (
        np.asarray(vertices, dtype=np.float64),
        np.asarray(segments, dtype=np.int64),
        densities,
        lithologies,
    )


def _lithology_mapped_data(lithologies: list[Optional[str]]) -> Optional[Any]:
    """Litología por segmento como `MappedData` + `Legend` (índice -1 = sin dato).

    Es la forma que OMF tiene de transportar una CATEGORÍA, y es la que hace que
    la unidad geológica llegue coloreable a Leapfrog/Vulcan en vez de perderse.
    """
    import omf

    units = sorted({unit for unit in lithologies if unit})
    if not units:
        return None
    position = {unit: index for index, unit in enumerate(units)}
    indices = np.array(
        [position.get(unit, -1) if unit else -1 for unit in lithologies], dtype=np.int64
    )
    return omf.MappedData(
        name="Lithology",
        array=indices,
        legends=[omf.Legend(name="Lithology", values=omf.StringArray(array=units))],
        location="segments",
    )


def build_borehole_lineset(run_dir: Path, georef: OmfGeoref) -> Optional[Any]:
    """Trazas de sondaje como `LineSetElement` (un segmento por intervalo)."""
    import omf

    path = run_dir / "boreholes.json"
    if not path.exists():
        return None
    payload = _read_json(path)
    if not isinstance(payload, list) or not payload:
        return None

    vertices, segments, densities, lithologies = _borehole_segments(payload, georef)
    if len(segments) == 0:
        return None

    element = omf.LineSetElement(
        name="Sondajes",
        description=(
            "Intervalos de sondaje VERTICALES (limitacion declarada del contrato "
            "interno: los sondajes persistidos no guardan hole_id ni desviacion). "
            "Un segmento por intervalo. Z=0 es la superficie local."
        ),
        geometry=omf.LineSetGeometry(vertices=vertices, segments=segments),
    )
    data: list[Any] = []
    if any(value is not None for value in densities):
        filled = np.array(
            [np.nan if value is None else value for value in densities], dtype=np.float64
        )
        data.append(_scalar_data("Density_t_m3", filled, "segments"))
    lithology = _lithology_mapped_data(lithologies)
    if lithology is not None:
        data.append(lithology)
    if data:
        element.data = data
    return element


def _decode_f32(blob: str) -> np.ndarray:
    return np.frombuffer(base64.b64decode(blob), dtype="<f4").astype(np.float64)


def _decode_u32(blob: str) -> np.ndarray:
    return np.frombuffer(base64.b64decode(blob), dtype="<u4").astype(np.int64)


def _isosurface_vertices(level: dict[str, Any], center: dict[str, Any], georef: OmfGeoref) -> np.ndarray:
    """Deshace el espacio VISUAL del visor y lleva a (Este, Norte, arriba).

    `isosurface_service` entrega los vértices centrados y con flip-Y para
    Three.js: `vx = x_m - cx`, `vy = cy - y_m`, `vz = z_m - cz`. Se invierte
    exactamente eso con el `center_m` que el propio servicio publica.
    """
    flat = _decode_f32(level["positions_b64"]).reshape(-1, 3)
    x_m = flat[:, 0] + float(center["x"])
    y_m = float(center["y"]) - flat[:, 1]
    z_m = flat[:, 2] + float(center["z"])
    return np.column_stack([x_m + georef.easting0, z_m + georef.northing0, -y_m])


def build_isosurface_elements(
    project_id: str, run_id: str, georef: OmfGeoref, field: str = "density"
) -> tuple[list[Any], list[str]]:
    """Una `SurfaceElement` por nivel de isosuperficie.

    A diferencia del resto, esto NO es un artefacto persistido: se calcula al
    vuelo (marching cubes + suavizado Taubin), como hace el endpoint del visor.
    Los vértices van suavizados; se declara en la descripción del elemento.
    """
    import omf

    from services.isosurface_service import build_isosurface_response

    response = build_isosurface_response(project_id, run_id, field=field)
    warnings = list(response.get("warnings") or [])
    if response.get("error"):
        return [], warnings + [f"isosuperficies omitidas: {response['error']}"]

    center = response.get("center_m") or {"x": 0.0, "y": 0.0, "z": 0.0}
    elements: list[Any] = []
    for level in response.get("levels") or []:
        vertices = _isosurface_vertices(level, center, georef)
        triangles = _decode_u32(level["indices_b64"]).reshape(-1, 3)
        if len(vertices) == 0 or len(triangles) == 0:
            continue
        pct = int(round(float(level.get("fraction", 0.0)) * 100))
        elements.append(omf.SurfaceElement(
            name=f"Isosuperficie {pct}% del pico ({field})",
            description=(
                f"Nivel = {level.get('fraction')} x contraste pico "
                f"(valor {level.get('level_value')}). Vertices SUAVIZADOS (Taubin), "
                "no estan exactamente sobre la isosuperficie del marching cubes. "
                f"Volumen encerrado {level.get('enclosed_volume_m3')} m3."
            ),
            geometry=omf.SurfaceGeometry(vertices=vertices, triangles=triangles),
        ))
    return elements, warnings


# ═════════════════════════════════════════════════════════════════════════════
# 4. Proyecto completo y serialización
# ═════════════════════════════════════════════════════════════════════════════

def _project_description(
    project_id: str, run_id: str, spec: OmfGridSpec, georef: OmfGeoref, run_type: str
) -> str:
    return "\n".join([
        f"TerraQuantum {APP_VERSION} - mapeo OMF v{OMF_MAPPING_VERSION}",
        f"Proyecto {project_id} | Corrida {run_id} | Fisica: {run_type}",
        f"Generado {datetime.now(timezone.utc).isoformat()}",
        "",
        f"MALLA: {spec.nx} (Este) x {spec.nz} (Norte) x {spec.ny} (vertical), "
        f"celda cubica de {spec.block_size:g} m, profundidad {spec.depth_m:g} m.",
        f"ESPACIAL: {georef.describe()}",
        "DATUM VERTICAL: NO DEFINIDO. El eje Z es PROFUNDIDAD bajo la superficie "
        "local (Z=0 en superficie), NO altura sobre el nivel del mar.",
        "ORDEN DE CELDAS: U (Este) primero, luego V (Norte), luego W (arriba), "
        "segun la especificacion de OMF.",
        "",
        DISCLAIMER,
    ])


def build_omf_project(
    project_id: str, run_id: str, include_surfaces: bool = True
) -> tuple[Any, dict[str, Any]]:
    """Arma el `omf.Project` de la corrida y el manifiesto de lo que publicó."""
    import omf
    import polars as pl

    run_dir = get_run_dir(project_id, run_id)
    if not run_dir.exists():
        raise OmfExportError(f"Run no encontrada: {project_id}/{run_id}")

    parquet = run_dir / RUN_BLOCK_MODEL_FILENAME
    if not parquet.exists():
        raise OmfExportError(
            f"La corrida no tiene {RUN_BLOCK_MODEL_FILENAME}: no hay block model que exportar."
        )
    frame = pl.read_parquet(str(parquet))
    if not {"ix", "iy", "iz"}.issubset(set(frame.columns)):
        raise OmfExportError(
            "El block model de esta corrida no trae indices de celda (ix, iy, iz) — "
            "es la tabla DISPERSA que escribe la inversion conjunta. Su malla no es "
            "reconstruible desde disco y no se va a inventar una."
        )

    spec = load_grid_spec(project_id, run_id)
    georef = load_georef(project_id, run_id)
    run_type = str(frame["run_type"][0]) if "run_type" in frame.columns else "desconocido"

    volume = build_volume_element(frame, spec, georef, name="Block model TerraQuantum")
    elements: list[Any] = [volume]
    warnings: list[str] = []

    stations = build_station_pointset(run_dir, georef)
    if stations is not None:
        elements.append(stations)

    boreholes = build_borehole_lineset(run_dir, georef)
    if boreholes is not None:
        elements.append(boreholes)

    if include_surfaces:
        surfaces, iso_warnings = build_isosurface_elements(project_id, run_id, georef)
        elements.extend(surfaces)
        warnings.extend(iso_warnings)

    project = omf.Project(
        name=f"TerraQuantum {project_id} / {run_id}"[:250],
        description=_project_description(project_id, run_id, spec, georef, run_type),
        author="TerraQuantum",
        revision=APP_VERSION,
        units="m",
        elements=elements,
    )
    manifest = {
        "mapping_version": OMF_MAPPING_VERSION,
        "container_version": OMF_CONTAINER_VERSION,
        "terraquantum_version": APP_VERSION,
        "project_id": project_id,
        "run_id": run_id,
        "run_type": run_type,
        "grid": {
            "nx_east": spec.nx, "ny_depth": spec.ny, "nz_north": spec.nz,
            "block_size_m": spec.block_size, "n_cells": spec.n_cells,
        },
        "georeferenced": georef.is_absolute,
        "epsg": georef.epsg,
        "georef_source": georef.source,
        "vertical_datum": None,
        "elements": [
            {"name": element.name, "type": type(element).__name__}
            for element in elements
        ],
        "volume_attributes": [item.name for item in volume.data],
        "warnings": warnings,
        "disclaimer": DISCLAIMER,
    }
    return project, manifest


def export_run_to_omf(
    project_id: str, run_id: str, include_surfaces: bool = True
) -> tuple[bytes, str, dict[str, Any]]:
    """Serializa la corrida a bytes `.omf` listos para descargar.

    `omf.OMFWriter` sólo sabe escribir a una ruta de fichero (hace `seek`), así
    que se pasa por un temporal y se devuelven los bytes.
    """
    import omf

    clean_pid, clean_rid = clean_trace_context(project_id, run_id)
    if not clean_pid or not clean_rid:
        raise OmfExportError("project_id y run_id son requeridos.")

    project, manifest = build_omf_project(clean_pid, clean_rid, include_surfaces)
    if not project.validate():
        raise OmfExportError("El proyecto OMF construido no valida contra el esquema de omf.")

    with tempfile.TemporaryDirectory(prefix="tq_omf_") as tmp:
        target = Path(tmp) / "run.omf"
        omf.OMFWriter(project, str(target))
        payload = target.read_bytes()

    manifest["bytes"] = len(payload)
    safe = lambda value: "".join(
        char if char.isalnum() or char in {"-", "_"} else "_" for char in value
    )[:32]
    filename = f"terraquantum_{safe(clean_pid)}_{safe(clean_rid)}.omf"

    _log.info(
        "omf_export_ok",
        project_id=clean_pid, run_id=clean_rid, bytes=len(payload),
        elements=len(manifest["elements"]), georeferenced=manifest["georeferenced"],
    )
    return payload, filename, manifest
