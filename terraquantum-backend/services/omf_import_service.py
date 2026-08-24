"""
FASE 12 — Importación de Open Mining Format (OMF v1).
=====================================================

Lee un `.omf` de terceros (Leapfrog, Vulcan, Micromine, `omf`, `omf-rust`) y lo
entrega a la ingesta de sondajes que YA existe: devuelve un `BoreholeSurvey`,
exactamente el mismo contrato que produce `parse_borehole_csv`. Por eso el
endpoint de importación puede reutilizar `ParseBoreholeCsvResponse` sin inventar
un contrato nuevo, y el sondaje importado alimenta el anclaje de la inversión por
el mismo camino que un CSV.

ALCANCE DELIBERADO
──────────────────
Se CONSUMEN los `LineSetElement` (trazas de sondaje). Del resto de elementos
—volúmenes de bloques, superficies, nubes de puntos— se publica un INVENTARIO
honesto (qué son, cuántos vértices/celdas, qué atributos traen) y se declara que
TerraQuantum todavía no los consume. No se fabrica un consumidor que finja usarlos.

LAS TRES COSAS QUE ESTE MÓDULO SE NIEGA A INVENTAR
──────────────────────────────────────────────────
1. **Sondajes desviados.** El motor sólo representa pozos VERTICALES (limitación
   declarada en `BoreholeInterval`). Un pozo desviado NO se aplasta a vertical:
   se DESCARTA y se informa con su identificador. Colocar sus muestras en la
   vertical del collar inyectaría una mentira geométrica en un ancla de inversión.
2. **El origen horizontal.** Un OMF de terceros suele venir en UTM absoluto y el
   motor trabaja en metros locales. No se adivina el desplazamiento con un umbral
   mágico: o lo declara quien llama (`origin_easting`/`origin_northing`), o se
   toma del propio proyecto destino (`project_id`), o se pasan las coordenadas
   TAL CUAL y se avisa, publicando siempre la caja envolvente para que se vea.
3. **La profundidad.** OMF guarda cota (Z hacia arriba) y el motor quiere
   profundidad (+ hacia abajo). Sin datum vertical declarado, la profundidad se
   mide desde el COLLAR de cada pozo (su vértice más alto), y así se informa.

Autor: TerraQuantum Backend | Fase 12
"""
from __future__ import annotations

import shutil
import tempfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Optional

import numpy as np

from core.logging import get_logger
from schemas.geophysics_schema import BoreholeSample, BoreholeSurvey

_log = get_logger(__name__)

# Pistas de nombre para reconocer atributos en ficheros ajenos. La detección
# SIEMPRE se reporta en el resultado: nunca es silenciosa.
_DENSITY_HINTS = ("densit", "density", "dens", "rho", "sg", "specific_gravity")
_SUSCEPTIBILITY_HINTS = ("suscep", "susc", "kappa", "chi", "mag_susc")
_LITHOLOGY_HINTS = ("lith", "litolog", "rock", "geol", "unit", "domain", "formation")

# Tolerancia por defecto de verticalidad (m). Por debajo de esto la desviación
# horizontal se considera ruido de la traza, no un pozo dirigido.
DEFAULT_DEVIATION_TOLERANCE_M = 1.0


class OmfImportError(ValueError):
    """El fichero no es un OMF legible o no contiene nada importable."""


@dataclass(frozen=True)
class OmfElementSummary:
    """Una línea del inventario honesto del fichero."""

    name: str
    kind: str
    n_vertices: int
    n_primitives: int
    attributes: tuple[str, ...]
    consumed: bool
    note: str


@dataclass
class OmfImportResult:
    survey: BoreholeSurvey
    inventory: list[OmfElementSummary] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    stats: dict[str, Any] = field(default_factory=dict)


# ═════════════════════════════════════════════════════════════════════════════
# 1. Lectura del contenedor
# ═════════════════════════════════════════════════════════════════════════════

def read_omf_project(data: bytes) -> Any:
    """Deserializa los bytes de un `.omf`.

    `omf.OMFReader` necesita un fichero con `seek`, así que se pasa por un
    temporal. Se traduce cualquier fallo del contenedor a un error propio con
    mensaje accionable: el `ValueError('Invalid OMF file')` crudo de una librería
    de 2019 no le dice nada al usuario que subió el fichero equivocado.

    ⚠️ GOTCHA DE WINDOWS, MEDIDO: si se le pasa una RUTA, `OMFReader` abre el
    fichero y NO lo cierra nunca — sólo lo cierra su `__del__`. Con el fichero
    aún abierto, borrar el directorio temporal revienta con
    `PermissionError [WinError 32]`, y eso convertía un 422 limpio («esto no es
    un OMF») en un 500. TerraQuantum es local-first sobre Windows, así que aquí
    se le pasa un descriptor que ABRIMOS Y CERRAMOS nosotros, y la limpieza no
    puede tumbar la petición.
    """
    import omf

    if not data:
        raise OmfImportError("El fichero OMF esta vacio.")

    tmp_dir = Path(tempfile.mkdtemp(prefix="tq_omf_in_"))
    target = tmp_dir / "input.omf"
    try:
        target.write_bytes(data)
        with target.open("rb") as handle:
            return omf.OMFReader(handle).get_project()
    except ValueError as exc:
        raise OmfImportError(
            f"No es un fichero OMF v1 legible ({exc}). TerraQuantum lee el "
            "contenedor OMF-v0.9.0 que escriben omf 1.x, Leapfrog y Vulcan; "
            "un OMF 2.0 hay que convertirlo antes."
        ) from exc
    except OmfImportError:
        raise
    except Exception as exc:
        raise OmfImportError(f"El fichero OMF no se pudo leer: {exc}") from exc
    finally:
        shutil.rmtree(tmp_dir, ignore_errors=True)


def _attribute_names(element: Any) -> tuple[str, ...]:
    return tuple(str(item.name) for item in (getattr(element, "data", None) or []))


def _count_primitives(element: Any) -> tuple[int, int]:
    """(vértices, primitivas) del elemento, sin asumir que tenga geometría."""
    geometry = getattr(element, "geometry", None)
    if geometry is None:
        return 0, 0
    vertices = getattr(geometry, "vertices", None)
    n_vertices = 0
    if vertices is not None:
        n_vertices = int(len(np.asarray(vertices.array)))
    for attribute in ("segments", "triangles"):
        primitive = getattr(geometry, attribute, None)
        if primitive is not None:
            return n_vertices, int(len(np.asarray(primitive.array)))
    if hasattr(geometry, "num_cells"):
        return n_vertices, int(geometry.num_cells)
    return n_vertices, 0


def summarize_project(project: Any) -> list[OmfElementSummary]:
    """Inventario de TODO el fichero, marcando qué se consume y qué no."""
    summaries: list[OmfElementSummary] = []
    for element in project.elements:
        kind = type(element).__name__
        n_vertices, n_primitives = _count_primitives(element)
        consumed = kind == "LineSetElement"
        summaries.append(OmfElementSummary(
            name=str(element.name),
            kind=kind,
            n_vertices=n_vertices,
            n_primitives=n_primitives,
            attributes=_attribute_names(element),
            consumed=consumed,
            note=(
                "trazas de sondaje: se importan"
                if consumed
                else "TerraQuantum todavia no consume este tipo de elemento"
            ),
        ))
    return summaries


# ═════════════════════════════════════════════════════════════════════════════
# 2. Reconstrucción de pozos a partir de segmentos
# ═════════════════════════════════════════════════════════════════════════════

def group_segments_into_holes(segments: np.ndarray) -> list[list[int]]:
    """Agrupa los segmentos de un LineSet en pozos por CONECTIVIDAD.

    Un OMF puede traer un sondaje como una cadena de segmentos que comparten
    vértices, o como intervalos sueltos. Agrupar por vértice compartido cubre
    ambos casos sin inventar un criterio de proximidad.
    """
    parent: dict[int, int] = {}

    def find(node: int) -> int:
        while parent.setdefault(node, node) != node:
            parent[node] = parent[parent[node]]
            node = parent[node]
        return node

    def union(a: int, b: int) -> None:
        root_a, root_b = find(a), find(b)
        if root_a != root_b:
            parent[root_b] = root_a

    for start, end in segments:
        union(int(start), int(end))

    groups: dict[int, list[int]] = {}
    for index, (start, _end) in enumerate(segments):
        groups.setdefault(find(int(start)), []).append(index)
    return list(groups.values())


def _segment_values(element: Any, n_segments: int) -> dict[str, list[Any]]:
    """Valores por segmento de cada atributo, ya resueltos los `MappedData`."""
    resolved: dict[str, list[Any]] = {}
    for item in getattr(element, "data", None) or []:
        if str(getattr(item, "location", "")) != "segments":
            continue
        raw = getattr(item.array, "array", item.array)
        values = list(raw)
        legends = getattr(item, "legends", None)
        if legends:
            lookup = list(legends[0].values)
            values = [
                lookup[int(v)] if 0 <= int(v) < len(lookup) else None for v in values
            ]
        if len(values) == n_segments:
            resolved[str(item.name)] = values
    return resolved


def _match_attribute(names: list[str], hints: tuple[str, ...]) -> Optional[str]:
    for name in names:
        lowered = name.lower()
        if any(hint in lowered for hint in hints):
            return name
    return None


def _as_float(value: Any) -> Optional[float]:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return None if not np.isfinite(number) else number


# ═════════════════════════════════════════════════════════════════════════════
# 3. Conversión de un pozo a muestras del contrato interno
# ═════════════════════════════════════════════════════════════════════════════

@dataclass(frozen=True)
class _AttributePlan:
    density: Optional[str]
    susceptibility: Optional[str]
    lithology: Optional[str]


def _plan_attributes(
    available: list[str],
    density_attribute: Optional[str],
    lithology_attribute: Optional[str],
) -> _AttributePlan:
    return _AttributePlan(
        density=density_attribute or _match_attribute(available, _DENSITY_HINTS),
        susceptibility=_match_attribute(available, _SUSCEPTIBILITY_HINTS),
        lithology=lithology_attribute or _match_attribute(available, _LITHOLOGY_HINTS),
    )


def _hole_samples(
    hole_id: str,
    segment_indices: list[int],
    vertices: np.ndarray,
    segments: np.ndarray,
    values: dict[str, list[Any]],
    plan: _AttributePlan,
    offset: tuple[float, float],
    surface_z: Optional[float] = None,
) -> list[BoreholeSample]:
    """Convierte los segmentos de UN pozo vertical en muestras del motor.

    `surface_z` es la cota que corresponde a profundidad 0. Si no se declara, la
    profundidad se mide desde el COLLAR del propio pozo — honesto pero distinto:
    un pozo cuyo primer tramo empieza a 20 m bajo la superficie entraría como
    tramo 0-140 en vez de 20-160. Por eso el exportador de TerraQuantum escribe
    Z=0 en la superficie y el importador lo puede recibir como `surface_z=0`.
    """
    used = np.unique(segments[segment_indices].ravel())
    collar_z = float(vertices[used, 2].max()) if surface_z is None else float(surface_z)
    east0, north0 = offset
    samples: list[BoreholeSample] = []

    for index in segment_indices:
        start, end = (int(v) for v in segments[index])
        top_z = max(float(vertices[start, 2]), float(vertices[end, 2]))
        bottom_z = min(float(vertices[start, 2]), float(vertices[end, 2]))
        depth_from = collar_z - top_z
        depth_to = collar_z - bottom_z
        if depth_to <= depth_from:
            continue  # segmento horizontal o degenerado: no es un tramo de pozo

        density = _as_float(values.get(plan.density, [None] * len(segments))[index]) if plan.density else None
        susceptibility = (
            _as_float(values.get(plan.susceptibility, [None] * len(segments))[index])
            if plan.susceptibility else None
        )
        lithology = values.get(plan.lithology, [None] * len(segments))[index] if plan.lithology else None
        lithology = str(lithology) if lithology not in (None, "") else None
        if density is None and susceptibility is None and lithology is None:
            continue  # el contrato interno rechaza tramos sin ninguna propiedad

        samples.append(BoreholeSample(
            hole_id=hole_id,
            x_m=float(vertices[start, 0]) - east0,
            z_m=float(vertices[start, 1]) - north0,
            depth_from_m=depth_from,
            depth_to_m=depth_to,
            sample_type="other",
            density_t_m3=density,
            susceptibility_si=susceptibility,
            lithology=lithology,
            comment="importado de OMF",
        ))
    return samples


def _horizontal_spread(vertices: np.ndarray, indices: np.ndarray) -> float:
    points = vertices[indices][:, :2]
    return float(np.max(np.linalg.norm(points - points[0], axis=1))) if len(points) else 0.0


# ═════════════════════════════════════════════════════════════════════════════
# 4. API pública
# ═════════════════════════════════════════════════════════════════════════════

def _resolve_offset(
    project_id: Optional[str],
    run_id: Optional[str],
    origin_easting: Optional[float],
    origin_northing: Optional[float],
    warnings: list[str],
) -> tuple[float, float]:
    """Desplazamiento a restar para pasar de UTM absoluto a metros locales."""
    if origin_easting is not None or origin_northing is not None:
        return float(origin_easting or 0.0), float(origin_northing or 0.0)

    if project_id and run_id:
        from services.omf_export_service import load_georef

        georef = load_georef(project_id, run_id)
        if georef.is_absolute:
            warnings.append(
                f"Origen tomado del proyecto destino: E={georef.easting0:.2f} "
                f"N={georef.northing0:.2f} (EPSG:{georef.epsg})."
            )
            return georef.easting0, georef.northing0

    warnings.append(
        "Coordenadas importadas TAL CUAL, sin restar origen. Si el OMF venia en "
        "UTM absoluto, declare origin_easting/origin_northing o un proyecto "
        "destino georreferenciado."
    )
    return 0.0, 0.0


def _import_lineset(
    element: Any,
    offset: tuple[float, float],
    tolerance: float,
    density_attribute: Optional[str],
    lithology_attribute: Optional[str],
    stats: dict[str, Any],
    warnings: list[str],
    surface_z: Optional[float] = None,
) -> list[BoreholeSample]:
    geometry = element.geometry
    vertices = np.asarray(geometry.vertices.array, dtype=np.float64)
    segments = np.asarray(geometry.segments.array, dtype=np.int64)
    if len(segments) == 0:
        return []

    values = _segment_values(element, len(segments))
    plan = _plan_attributes(list(values.keys()), density_attribute, lithology_attribute)
    stats.setdefault("attributes_detected", {})[str(element.name)] = {
        "density": plan.density,
        "susceptibility": plan.susceptibility,
        "lithology": plan.lithology,
        "available": sorted(values.keys()),
    }

    samples: list[BoreholeSample] = []
    for order, indices in enumerate(group_segments_into_holes(segments), start=1):
        used = np.unique(segments[indices].ravel())
        hole_id = f"{element.name}-{order}" if len(segments) > 1 else str(element.name)
        spread = _horizontal_spread(vertices, used)
        if spread > tolerance:
            stats["deviated_holes"] = stats.get("deviated_holes", 0) + 1
            warnings.append(
                f"Sondaje '{hole_id}' DESCARTADO: desviacion horizontal de "
                f"{spread:.1f} m (> {tolerance:g} m). El motor solo representa "
                "pozos verticales y aplastarlo falsearia su geometria."
            )
            continue
        samples.extend(_hole_samples(
            hole_id, indices, vertices, segments, values, plan, offset, surface_z
        ))
    return samples


def import_omf_boreholes(
    data: bytes,
    *,
    project_id: Optional[str] = None,
    run_id: Optional[str] = None,
    origin_easting: Optional[float] = None,
    origin_northing: Optional[float] = None,
    density_attribute: Optional[str] = None,
    lithology_attribute: Optional[str] = None,
    deviation_tolerance_m: float = DEFAULT_DEVIATION_TOLERANCE_M,
    surface_z: Optional[float] = None,
    crs: str = "local",
) -> OmfImportResult:
    """Lee un OMF y devuelve sus sondajes en el contrato interno del motor.

    El resultado incluye SIEMPRE el inventario completo del fichero, para que el
    usuario vea qué venía dentro y qué se usó — aunque no se importe nada.
    """
    project = read_omf_project(data)
    inventory = summarize_project(project)
    warnings: list[str] = []
    stats: dict[str, Any] = {"deviated_holes": 0}

    offset = _resolve_offset(project_id, run_id, origin_easting, origin_northing, warnings)

    samples: list[BoreholeSample] = []
    for element in project.elements:
        if type(element).__name__ != "LineSetElement":
            continue
        samples.extend(_import_lineset(
            element, offset, deviation_tolerance_m,
            density_attribute, lithology_attribute, stats, warnings, surface_z,
        ))

    if surface_z is None and samples:
        warnings.append(
            "Profundidades medidas desde el COLLAR de cada pozo: el fichero no "
            "declara datum vertical. Si sabe a que cota corresponde profundidad 0, "
            "declare surface_z (para un OMF generado por TerraQuantum, surface_z=0)."
        )

    if not any(item.consumed for item in inventory):
        warnings.append(
            "El fichero OMF no trae ningun LineSet: no hay trazas de sondaje que "
            "importar. Vea el inventario para saber que si contiene."
        )
    elif not samples:
        warnings.append(
            "Se encontraron trazas de sondaje pero ninguna aporto un tramo "
            "utilizable (sin densidad, sin susceptibilidad y sin litologia, o "
            "geometria degenerada)."
        )

    bounds = _bounds(project)
    stats.update({
        "n_elements": len(inventory),
        "n_samples": len(samples),
        "n_holes": len({sample.hole_id for sample in samples}),
        "origin_applied": {"easting": offset[0], "northing": offset[1]},
        "bounds_raw": bounds,
    })

    _log.info(
        "omf_import_ok",
        n_elements=len(inventory), n_samples=len(samples),
        deviated=stats["deviated_holes"],
    )
    return OmfImportResult(
        survey=BoreholeSurvey(holes=samples, crs=crs, datum_elevation_m=0.0),
        inventory=inventory,
        warnings=warnings,
        stats=stats,
    )


def _bounds(project: Any) -> Optional[dict[str, float]]:
    """Caja envolvente de los vértices del fichero, en sus coordenadas ORIGINALES.

    Se publica siempre: es lo que le permite a un usuario ver de un vistazo si su
    OMF venía en UTM absoluto o en metros locales, sin que el backend lo adivine.
    """
    clouds = [
        np.asarray(element.geometry.vertices.array, dtype=np.float64)
        for element in project.elements
        if getattr(getattr(element, "geometry", None), "vertices", None) is not None
    ]
    clouds = [cloud for cloud in clouds if len(cloud)]
    if not clouds:
        return None
    stacked = np.vstack(clouds)
    return {
        "x_min": float(stacked[:, 0].min()), "x_max": float(stacked[:, 0].max()),
        "y_min": float(stacked[:, 1].min()), "y_max": float(stacked[:, 1].max()),
        "z_min": float(stacked[:, 2].min()), "z_max": float(stacked[:, 2].max()),
    }
