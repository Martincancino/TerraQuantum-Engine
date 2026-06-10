import logging
import math
from typing import Optional

from schemas.gravity_import_schema import AutoGrid
from services.octree_mesh_builder import compute_octree_params, should_auto_use_treemesh

logger = logging.getLogger(__name__)


R10_LIMIT = 200_000
MIN_BLOCK_SIZE = 25.0
MAX_BLOCK_SIZE = 10_000.0
MIN_GRID_CELLS = 4
MIN_DEPTH_M = 1_000.0
MAX_DEPTH_M = 100_000.0
MAX_R10_ITERATIONS = 100

# HITO 5 — Scale-aware meshing (Bug de Bushveld).
# Profundidad de sensibilidad confiable ≈ L_max / DEPTH_SENS_FACTOR (regla geofísica,
# Li & Oldenburg). El antiguo factor 0.6 sobre-profundizaba; L_max/3 es el estándar.
DEPTH_SENS_FACTOR = 3.0
# Umbral de régimen regional (por encima, el cap fijo de 100 km truncaba el modelo).
REGIONAL_SCALE_M = 50_000.0


def _clamp(value: float, min_value: float, max_value: float) -> float:
    return max(min_value, min(max_value, value))


def _initial_block_size(
    x_extent_m: float,
    z_extent_m: float,
    observation_count: int,
    mean_spacing_m: Optional[float] = None,
) -> tuple[float, list[str]]:
    warnings: list[str] = []
    safe_x = max(float(x_extent_m), 0.0)
    safe_z = max(float(z_extent_m), 0.0)
    safe_count = max(int(observation_count), 0)
    area_m2 = safe_x * safe_z

    if mean_spacing_m is not None and mean_spacing_m > 0:
        mean_spacing = float(mean_spacing_m)
    elif area_m2 > 0 and safe_count > 0:
        mean_spacing = math.sqrt(area_m2 / safe_count)
    else:
        mean_spacing = MIN_BLOCK_SIZE * 2.0
        warnings.append("Extent u observaciones insuficientes; block_size usa fallback seguro.")

    # Fase 2: MIN_BLOCK_SIZE dinámico — Li & Oldenburg (1998) recomiendan celda ≤ spacing/4
    # para resolución adecuada. Mínimo absoluto 10 m evita celdas degeneradas en surveys finos.
    dynamic_min = max(mean_spacing / 4.0, 10.0)
    block_size = _clamp(mean_spacing / 2.0, dynamic_min, MAX_BLOCK_SIZE)
    return block_size, warnings


def _dimensions(
    x_extent_m: float,
    z_extent_m: float,
    depth_m: float,
    block_size_m: float,
) -> tuple[int, int, int, int]:
    safe_block = max(float(block_size_m), 1e-9)
    nx = max(MIN_GRID_CELLS, int(math.ceil(max(float(x_extent_m), 0.0) / safe_block)))
    ny = max(MIN_GRID_CELLS, int(math.ceil(max(float(depth_m), 0.0) / safe_block)))
    nz = max(MIN_GRID_CELLS, int(math.ceil(max(float(z_extent_m), 0.0) / safe_block)))
    return nx, ny, nz, nx * ny * nz


def _apply_r10(
    block_size_m: float,
    x_extent_m: float,
    z_extent_m: float,
    depth_m: float,
    r10_limit: int = R10_LIMIT,
) -> tuple[float, int, int, int, int, bool, int, list[str]]:
    warnings: list[str] = []
    nx, ny, nz, voxel_count = _dimensions(x_extent_m, z_extent_m, depth_m, block_size_m)
    voxel_count_before_r10 = voxel_count
    adjusted_for_r10 = False
    r10_iterations = 0

    while voxel_count > r10_limit and r10_iterations < MAX_R10_ITERATIONS:
        block_size_m *= 1.1
        r10_iterations += 1
        adjusted_for_r10 = True
        nx, ny, nz, voxel_count = _dimensions(x_extent_m, z_extent_m, depth_m, block_size_m)

    if voxel_count > r10_limit:
        adjusted_for_r10 = True
        block_size_m = max(
            float(x_extent_m) / MIN_GRID_CELLS if x_extent_m > 0 else block_size_m,
            float(z_extent_m) / MIN_GRID_CELLS if z_extent_m > 0 else block_size_m,
            float(depth_m) / MIN_GRID_CELLS if depth_m > 0 else block_size_m,
            block_size_m,
        )
        nx, ny, nz, voxel_count = _dimensions(x_extent_m, z_extent_m, depth_m, block_size_m)
        warnings.append("R-10 requirio fallback extremo para garantizar voxel_count <= 200000.")

    if adjusted_for_r10:
        warnings.append("block_size_m ajustado para cumplir R-10: nx*ny*nz <= 200000.")

    return (
        block_size_m,
        nx,
        ny,
        nz,
        voxel_count,
        adjusted_for_r10,
        voxel_count_before_r10,
        r10_iterations,
        warnings,
    )


def compute_auto_grid(
    x_extent_m: float,
    z_extent_m: float,
    observation_count: int,
    quality_label: str,
    mean_spacing_m: Optional[float] = None,
    r10_limit: int = R10_LIMIT,
) -> AutoGrid:
    warnings: list[str] = []
    rationale: list[str] = []
    safe_x = max(float(x_extent_m), 0.0)
    safe_z = max(float(z_extent_m), 0.0)
    safe_count = max(int(observation_count), 0)

    block_size, block_warnings = _initial_block_size(
        safe_x,
        safe_z,
        safe_count,
        mean_spacing_m=mean_spacing_m,
    )
    warnings.extend(block_warnings)
    rationale.append("block_size_m inicial = mean_spacing_m / 2 con caps 25..10000 m.")

    # ── HITO 5: Scale-Aware Meshing (Paso 1) ─────────────────────────────────
    # L_max = extensión horizontal máxima del survey.
    max_extent = max(safe_x, safe_z)
    is_regional = max_extent > REGIONAL_SCALE_M
    # Profundidad = L_max / 3 (sensibilidad geofísica confiable), NO 0.6·L_max.
    # El tope deja de ser 100 km FIJO: en surveys regionales escala con el survey
    # (max(100km, L_max)) para no truncar el modelo. En L_max/3 el cap nunca llega
    # a morder, pero protege ante extents degenerados.
    depth_cap = max(MAX_DEPTH_M, max_extent)
    depth_m = _clamp(max_extent / DEPTH_SENS_FACTOR, MIN_DEPTH_M, depth_cap)
    rationale.append(
        f"depth_m = clamp(max_extent / {DEPTH_SENS_FACTOR:g}, "
        f"{MIN_DEPTH_M:g}, max(100000, max_extent)) [scale-aware]."
    )
    logger.info(
        "Survey Scale: %s (L=%.0fkm). Mesh adjusted dynamically "
        "(depth=L/%g=%.1fkm, cap=%.0fkm). Depth Weighting z0 calibrated "
        "(z0=block_size/2, Li & Oldenburg).",
        "Regional" if is_regional else "Local",
        max_extent / 1000.0,
        DEPTH_SENS_FACTOR,
        depth_m / 1000.0,
        depth_cap / 1000.0,
    )

    if safe_x <= 0 or safe_z <= 0:
        warnings.append("Extent canonico degenerado; se aplicaron minimos de grilla.")
    if safe_count <= 0:
        warnings.append("observation_count es cero; auto_grid usa fallback seguro.")
    if quality_label in {"BAJA", "INSUFICIENTE"}:
        warnings.append(f"quality_label={quality_label}; revisar grilla antes de uso productivo.")

    (
        block_size,
        nx,
        ny,
        nz,
        voxel_count,
        adjusted_for_r10,
        voxel_count_before_r10,
        r10_iterations,
        r10_warnings,
    ) = _apply_r10(block_size, safe_x, safe_z, depth_m, r10_limit=r10_limit)
    warnings.extend(r10_warnings)
    rationale.append("R-10 aplicado por incremento iterativo de block_size_m.")

    if voxel_count > r10_limit:
        warnings.append("No se pudo cumplir R-10; revisar extents de entrada.")

    mean_spacing = (
        float(mean_spacing_m)
        if mean_spacing_m is not None and mean_spacing_m > 0
        else math.sqrt((safe_x * safe_z) / safe_count)
        if safe_x > 0 and safe_z > 0 and safe_count > 0
        else block_size * 2.0
    )
    # El cutoff debe cubrir al menos la profundidad del modelo: un vóxel
    # directamente bajo una estación a profundidad z requiere cutoff >= z para
    # ser sensado. Con solo max(3·block, 2·spacing), los surveys dispersos
    # quedaban con >80% de vóxeles muertos y misfit >80% (caso Laguna del Maule).
    cutoff_radius_m = max(block_size * 3.0, mean_spacing * 2.0, float(depth_m))
    rationale.append(
        "cutoff_radius_m = max(block_size_m * 3, mean_spacing_m * 2, depth_m) "
        "— cubre la profundidad del modelo para evitar voxeles muertos."
    )

    # Sprint 3 — parámetros Octree calibrados (base, refine, radius, min_cell)
    oct_p = compute_octree_params(
        block_size_m=block_size,
        x_extent_m=safe_x,
        z_extent_m=safe_z,
        mean_spacing_m=mean_spacing,
        n_sensors=safe_count,
    )
    recommended_treemesh = should_auto_use_treemesh(voxel_count, safe_x, safe_z)

    return AutoGrid(
        block_size_m=block_size,
        nx=nx,
        ny=ny,
        nz=nz,
        voxel_count=voxel_count,
        depth_m=depth_m,
        cutoff_radius_m=cutoff_radius_m,
        r10_limit=r10_limit,
        adjusted_for_r10=adjusted_for_r10,
        voxel_count_before_r10=voxel_count_before_r10,
        r10_iterations=r10_iterations,
        warnings=list(dict.fromkeys(warnings)),
        rationale=rationale,
        octree_params=oct_p.as_dict(),
        recommended_use_treemesh=recommended_treemesh,
    )
