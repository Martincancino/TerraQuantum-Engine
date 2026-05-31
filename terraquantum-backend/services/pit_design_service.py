import json
import os
import uuid

import numpy as np
import polars as pl
import trimesh
from fastapi import HTTPException

from engine import LerchsGrossmannEngine
from scheduler import ProductionScheduler
from pit_mesh import (
    build_benched_mesh,
    build_column_topography,
    build_excavation_surface,
    quantize_surface_to_benches,
)

from core.config import (
    MODELS_DIR,
    MODELS_ROUTE_PREFIX,
    ensure_runtime_dirs,
)
from core.block_model_store import (
    get_run_metrics_path,
    get_run_schedule_path,
    resolve_mine_design_block_model_reference,
)
from core.logging import get_logger
from schemas.pit_design_schema import PitRequest
from services.block_model_service import ensure_visual_columns, get_index_columns

_log = get_logger(__name__)


def make_json_safe(value):
    if isinstance(value, dict):
        return {key: make_json_safe(item) for key, item in value.items()}
    if isinstance(value, list):
        return [make_json_safe(item) for item in value]
    if isinstance(value, tuple):
        return [make_json_safe(item) for item in value]
    if isinstance(value, np.integer):
        return int(value)
    if isinstance(value, np.floating):
        return float(value)
    if isinstance(value, np.ndarray):
        return make_json_safe(value.tolist())
    return value


def scene_has_geometry(scene: trimesh.Scene) -> bool:
    """Check whether a trimesh Scene contains at least one real geometry."""
    try:
        geom_dict = scene.geometry
        if not geom_dict:
            return False
        for mesh in geom_dict.values():
            if hasattr(mesh, "vertices") and len(mesh.vertices) > 0:
                return True
        return False
    except Exception:
        return False


def build_fallback_phase_block_scene(
    df: pl.DataFrame,
    phase_1d: np.ndarray,
    req: PitRequest,
    ix_col: str,
    iy_col: str,
    iz_col: str,
    nx: int,
    ny: int,
    nz: int,
) -> trimesh.Scene:
    """
    Build a simple GLB scene using box primitives for each mined block,
    grouped by phase. This is a visual fallback when benched mesh generation
    produces empty geometry (common with small/synthetic models).
    """
    scene = trimesh.Scene()

    bx = float(req.block_size_x)
    by = float(req.block_size_y)
    bz = float(req.block_size_z)

    # Compute block centre coordinates from index columns if x/y/z are absent.
    has_xyz = ("x" in df.columns and "y" in df.columns and "z" in df.columns)

    if has_xyz:
        cx = df["x"].to_numpy().astype(np.float64)
        cy = df["y"].to_numpy().astype(np.float64)
        cz = df["z"].to_numpy().astype(np.float64)
    else:
        cx = (df[ix_col].to_numpy().astype(np.float64) + 0.5) * bx
        cy = (df[iy_col].to_numpy().astype(np.float64) + 0.5) * by
        cz = (df[iz_col].to_numpy().astype(np.float64) + 0.5) * bz

    # Centre offset so the model is centred at origin
    x_off = (nx * bx) / 2.0
    z_off = (nz * bz) / 2.0

    phase_colors = {
        1: [210, 105, 30, 200],
        2: [169, 169, 169, 200],
        3: [105, 105, 105, 200],
    }

    unique_phases = sorted(set(int(p) for p in phase_1d if p > 0))

    for phase_num in unique_phases:
        mask = phase_1d == phase_num
        indices = np.where(mask)[0]

        if len(indices) == 0:
            continue

        meshes = []
        for idx in indices:
            box_mesh = trimesh.creation.box(extents=[bx, by, bz])
            # Position: x,z centred; y inverted (surface at 0, depth negative)
            tx = float(cx[idx]) - x_off
            ty = -float(cy[idx])  # Y-up convention: depth is negative
            tz = float(cz[idx]) - z_off
            box_mesh.apply_translation([tx, ty, tz])
            meshes.append(box_mesh)

        if not meshes:
            continue

        combined = trimesh.util.concatenate(meshes)
        color = phase_colors.get(phase_num, [128, 128, 128, 200])
        combined.visual.vertex_colors = color
        scene.add_geometry(combined, geom_name=f"Fase_{phase_num}_fallback")

    # ── Aggregated shell for "Pit Shell Conceptual" (viewMode 2) ──
    # The frontend assigns phaseIdx=2 to any mesh whose name does NOT
    # contain "Fase_1" or "Fase_2".  We create a single combined mesh
    # of every mined block so that the pit is visible in viewMode 2.
    all_mined_mask = phase_1d > 0
    all_mined_indices = np.where(all_mined_mask)[0]

    if len(all_mined_indices) > 0:
        shell_meshes = []
        for idx in all_mined_indices:
            box_mesh = trimesh.creation.box(extents=[bx, by, bz])
            tx = float(cx[idx]) - x_off
            ty = -float(cy[idx])
            tz = float(cz[idx]) - z_off
            box_mesh.apply_translation([tx, ty, tz])
            shell_meshes.append(box_mesh)

        shell_combined = trimesh.util.concatenate(shell_meshes)
        shell_combined.visual.vertex_colors = [80, 160, 200, 220]
        scene.add_geometry(shell_combined, geom_name="Fase_3_fallback_final_shell")
        _log.info("fallback_shell_added")

    return scene


def prepare_dense_grid(df: pl.DataFrame, ix_col: str, iy_col: str, iz_col: str,
                       nx: int, ny: int, nz: int, req: PitRequest) -> pl.DataFrame:
    grid_idx = "__grid_idx"
    expected_rows = nx * ny * nz

    df = df.with_columns(
        (
            pl.col(ix_col)
            + (pl.col(iy_col) * nx)
            + (pl.col(iz_col) * nx * ny)
        ).cast(pl.Int64).alias(grid_idx)
    )

    if len(df) == expected_rows:
        return df.sort(grid_idx).drop(grid_idx)

    _log.info("block_model_sparse", rows=len(df), expected=expected_rows)

    ix = np.tile(np.arange(nx, dtype=np.int64), ny * nz)
    iy = np.tile(np.repeat(np.arange(ny, dtype=np.int64), nx), nz)
    iz = np.repeat(np.arange(nz, dtype=np.int64), nx * ny)

    full_grid = pl.DataFrame(
        {
            ix_col: ix,
            iy_col: iy,
            iz_col: iz,
            grid_idx: np.arange(expected_rows, dtype=np.int64),
        }
    )

    df = full_grid.join(df.drop(grid_idx), on=[ix_col, iy_col, iz_col], how="left")

    fill_exprs = []
    if "x" in df.columns:
        fill_exprs.append(
            pl.col("x").fill_null((pl.col(ix_col) + 0.5) * req.block_size_x).alias("x")
        )
    if "y" in df.columns:
        fill_exprs.append(
            pl.col("y").fill_null((pl.col(iy_col) + 0.5) * req.block_size_y).alias("y")
        )
    if "z" in df.columns:
        fill_exprs.append(
            pl.col("z").fill_null((pl.col(iz_col) + 0.5) * req.block_size_z).alias("z")
        )

    for col in df.columns:
        if col in {ix_col, iy_col, iz_col, grid_idx, "x", "y", "z"}:
            continue
        if df.schema[col].is_numeric():
            fill_exprs.append(pl.col(col).fill_null(0).alias(col))

    if fill_exprs:
        df = df.with_columns(fill_exprs)

    return df.sort(grid_idx).drop(grid_idx)


def write_run_pit_snapshots(req: PitRequest, metrics: dict, schedule: list, metadata: dict):
    metrics_path = get_run_metrics_path(
        project_id=req.project_id,
        run_id=req.run_id,
    )
    schedule_path = get_run_schedule_path(
        project_id=req.project_id,
        run_id=req.run_id,
    )

    if metrics_path is None or schedule_path is None:
        return

    metrics_payload = {
        **metrics,
        **metadata,
    }

    metrics_path.parent.mkdir(parents=True, exist_ok=True)

    with metrics_path.open("w", encoding="utf-8") as f:
        json.dump(make_json_safe(metrics_payload), f, indent=2)

    with schedule_path.open("w", encoding="utf-8") as f:
        json.dump(make_json_safe(schedule), f, indent=2)


def resolve_block_file(file_name: str, project_id: str = None, run_id: str = None) -> str:
    return str(
        resolve_mine_design_block_model_reference(
            file_name=file_name,
            project_id=project_id,
            run_id=run_id,
        ).path
    )


def generate_pit_design(req: PitRequest):
    _log.info("pit_design_start", project_id=req.project_id, run_id=req.run_id)

    if not req.file and not req.project_id and not req.run_id:
        raise HTTPException(
            status_code=400,
            detail="Debe proveer project_id/run_id o file explícito. No existe fallback silencioso a modelo legacy.",
        )

    # Solo uno de project_id/run_id presente → referencia incompleta → error.
    if bool(req.project_id) != bool(req.run_id):
        raise HTTPException(
            status_code=400,
            detail="project_id y run_id deben proporcionarse juntos.",
        )

    ensure_runtime_dirs()

    job_id = str(uuid.uuid4())

    try:
        block_model_ref = resolve_mine_design_block_model_reference(
            file_name=req.file,
            project_id=req.project_id,
            run_id=req.run_id,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    file_path = str(block_model_ref.path)

    if not os.path.exists(file_path):
        if req.project_id and req.run_id:
            raise HTTPException(
                status_code=404,
                detail=f"No se encontró block_model.parquet para project_id={req.project_id} run_id={req.run_id}",
            )
        raise HTTPException(
            status_code=404,
            detail=f"No existe el archivo de block model: {req.file}",
        )

    df = pl.read_parquet(file_path)
    df = ensure_visual_columns(df)

    try:
        ix_col, iy_col, iz_col = get_index_columns(df)
    except ValueError as exc:
        return {
            "status": "error",
            "detail": str(exc),
        }

    nx = int(df[ix_col].max()) + 1
    ny = int(df[iy_col].max()) + 1
    nz = int(df[iz_col].max()) + 1

    df = prepare_dense_grid(df, ix_col, iy_col, iz_col, nx, ny, nz, req)

    grade = df["grade"].to_numpy()
    density = df["density"].to_numpy()
    tonnage = df["tonnage"].to_numpy()
    domain = df["domain"].to_numpy()

    if "resource_class" in df.columns:
        resource_class = df["resource_class"].to_numpy()
    else:
        resource_class = np.ones_like(grade, dtype=np.int8)

    if req.exclude_inferred:
        _log.info("exclude_inferred_resources")
        grade = np.where(resource_class == 3, 0.0, grade)

    rock_mask = density.reshape((nx, ny, nz), order="F") > 0
    topography = build_column_topography(rock_mask)

    domain_3d = domain.reshape((nx, ny, nz), order="F")

    angle_matrix = np.where(
        domain_3d == 1,
        38.0,
        req.pit_angle,
    ).astype(np.float32)

    pit_exit_x = (nx * req.block_size_x) / 2.0
    pit_exit_z = (nz * req.block_size_z) / 2.0

    x_grid_3d, y_grid_3d, z_grid_3d = np.mgrid[0:nx, 0:ny, 0:nz]

    dist_horiz = np.sqrt(
        ((x_grid_3d * req.block_size_x) - pit_exit_x) ** 2
        + ((z_grid_3d * req.block_size_z) - pit_exit_z) ** 2
    )

    dist_vert_ramp = (y_grid_3d * req.block_size_y) / req.ramp_gradient

    total_haul_dist = dist_horiz + dist_vert_ramp

    costo_mina_real_3d = req.mining_cost + (
        total_haul_dist * req.haulage_cost_per_m
    )

    costo_mina_real_1d = costo_mina_real_3d.flatten(order="F")

    revenue_factors = [0.65, 0.85, 1.0]

    phase_colors = [
        [210, 105, 30, 255],
        [169, 169, 169, 255],
        [105, 105, 105, 255],
    ]

    scene = trimesh.Scene()
    phase_1d = np.zeros(nx * ny * nz, dtype=np.int8)
    final_costos = np.zeros(nx * ny * nz)

    for idx, rf in enumerate(revenue_factors):
        current_phase_number = idx + 1

        ingresos = tonnage * (grade / 100.0) * req.recovery * (req.price * rf)

        costos = (tonnage * costo_mina_real_1d) + (
            tonnage * req.processing_cost * (domain > 0)
        )

        final_costos = costos

        profit_1d = ingresos - costos
        profit_3d = profit_1d.reshape((nx, ny, nz), order="F")

        # El LG engine usa INF=1e12 como capacidad interna de arcos de precedencia.
        # Con blockSize regional (ej. 1552m), el profit por bloque puede superar 1e12,
        # haciendo que el max-flow falle silenciosamente (0 bloques extraídos).
        # La normalización preserva el signo y el orden relativo de los bloques.
        _profit_max_abs = float(np.max(np.abs(profit_3d)))
        _LG_ENGINE_INF = 1e12
        if _profit_max_abs > _LG_ENGINE_INF / 100:
            profit_3d_lg = profit_3d / (_profit_max_abs / (_LG_ENGINE_INF / 1000))
        else:
            profit_3d_lg = profit_3d

        engine = LerchsGrossmannEngine(
            profit_3d_lg,
            req.block_size_x,
            req.block_size_y,
            req.block_size_z,
            angle_matrix,
        )

        mined_mask, _ = engine.optimize_with_maxflow()
        mask_1d = mined_mask.flatten(order="F")

        phase_1d = np.where(
            (mask_1d == True) & (phase_1d == 0),
            current_phase_number,
            phase_1d,
        )

        surface = build_excavation_surface(mined_mask, topography)
        surface = quantize_surface_to_benches(
            surface,
            req.block_size_x,
            req.bench_height,
        )

        current_color = phase_colors[idx % len(phase_colors)]

        mesh = build_benched_mesh(
            surface,
            req.block_size_x,
            req.bench_height,
            req.pit_angle,
            req.berm_width,
            color=current_color,
        )

        if not mesh.is_empty:
            scene.add_geometry(mesh, geom_name=f"Fase_{current_phase_number}")

    _log.info("phases_generated_starting_scheduler")

    ingresos_reales = tonnage * (grade / 100.0) * req.recovery * req.price
    profit_final = ingresos_reales - final_costos

    df = df.with_columns(
        [
            pl.Series(name="phase", values=phase_1d),
            pl.Series(name="profit", values=profit_final),
        ]
    )

    scheduler = ProductionScheduler(
        df=df,
        base_p_cap=req.p_cap,
        discount_rate=req.discount_rate,
        fleet_size=req.fleet_size,
    )

    df_scheduled, yearly_metrics, total_npv = scheduler.run()

    # ── Determine pit_mesh_mode and handle empty scene ──
    pit_mesh_mode = "benched_mesh"

    if not scene_has_geometry(scene):
        mined_block_count_for_fallback = int(np.sum(phase_1d > 0))
        _log.info("benched_mesh_empty_using_fallback", mined_blocks=mined_block_count_for_fallback)

        if mined_block_count_for_fallback > 0:
            scene = build_fallback_phase_block_scene(
                df=df,
                phase_1d=phase_1d,
                req=req,
                ix_col=ix_col,
                iy_col=iy_col,
                iz_col=iz_col,
                nx=nx,
                ny=ny,
                nz=nz,
            )
            pit_mesh_mode = "fallback_block_shell"

    # ── Quality guardrail for project_run sources ──
    # A fallback block shell is acceptable for legacy/demo models, but a real
    # project_run corrida should not present cubes as a defensible pit design.
    ref_metadata = block_model_ref.metadata()
    source_mode = ref_metadata.get("storageMode", "legacy")
    total_blocks = nx * ny * nz
    mined_block_count = int(np.sum(phase_1d > 0))

    is_low_resolution = (
        total_blocks < 500
        or nx < 8
        or ny < 8
        or nz < 8
        or mined_block_count == total_blocks
    )

    if source_mode == "project_run" and (pit_mesh_mode == "fallback_block_shell" or is_low_resolution):
        _log.warning(
            "low_resolution_run_pit_generated_with_caveat",
            nx=nx, ny=ny, nz=nz,
            total_blocks=total_blocks,
            mined_blocks=mined_block_count,
            pit_mesh_mode=pit_mesh_mode,
        )

    # ── Export GLB ──
    tmp_glb = MODELS_DIR / f"pit_{job_id}.glb.tmp"
    final_glb = MODELS_DIR / f"pit_{job_id}.glb"

    if not scene_has_geometry(scene):
        # Even the fallback produced nothing — return a structured error, not a 500.
        mask_final = phase_1d > 0
        return {
            "status": "error",
            "detail": "El pit conceptual calculó fases, pero no pudo construir geometría GLB visualizable.",
            "total_blocks": total_blocks,
            "mined_blocks": int(np.sum(mask_final)),
            "pit_mesh_mode": "none",
        }

    scene.export(str(tmp_glb), file_type="glb")
    os.rename(str(tmp_glb), str(final_glb))

    mask_final = phase_1d > 0

    ore_mask = (phase_1d > 0) & (domain > 0)
    waste_mask = (phase_1d > 0) & (domain == 0)
    ore_tonnage_sr = float(np.sum(tonnage[ore_mask]))
    waste_tonnage_sr = float(np.sum(tonnage[waste_mask]))
    strip_ratio = float(waste_tonnage_sr / ore_tonnage_sr) if ore_tonnage_sr > 0 else None

    mined_tonnage = float(np.sum(tonnage[mask_final]))

    valid = tonnage[mask_final] > 0

    mined_avg_grade = (
        float(
            np.average(
                grade[mask_final][valid],
                weights=tonnage[mask_final][valid],
            )
        )
        if np.any(valid)
        else 0.0
    )

    cutoff_grade = float(req.processing_cost / (req.recovery * req.price))

    final_metrics = {
        "npv": float(total_npv),
        "tonnage": mined_tonnage,
        "avg_grade": mined_avg_grade,
        "cutoff_grade": cutoff_grade,
        "total_blocks": int(np.sum(mask_final)),
        "lom_years": len(yearly_metrics),
        "schedule": yearly_metrics,
        "pit_mesh_mode": pit_mesh_mode,
        "strip_ratio": strip_ratio,
        "ore_tonnage": ore_tonnage_sr,
        "waste_tonnage": waste_tonnage_sr,
    }

    model_url = f"{MODELS_ROUTE_PREFIX}/pit_{job_id}.glb"

    extended_metadata = {
        "source_project_id": ref_metadata.get("projectId"),
        "source_run_id": ref_metadata.get("runId"),
        "source_block_model_path": ref_metadata.get("blockModelPath"),
        "source_mode": ref_metadata.get("storageMode"),
    }

    run_metadata = {
        **ref_metadata,
        **extended_metadata,
        "modelUrl": model_url,
        "jobId": job_id,
        "pit_mesh_mode": pit_mesh_mode,
    }

    write_run_pit_snapshots(
        req=req,
        metrics=final_metrics,
        schedule=yearly_metrics,
        metadata=run_metadata,
    )

    _log.info(
        "pit_design_done",
        npv_total=round(total_npv, 2),
        lom_years=len(yearly_metrics),
        pit_mesh_mode=pit_mesh_mode,
    )

    return {
        "jobId": job_id,
        "status": "done",
        "modelUrl": model_url,
        "metrics": final_metrics,
        "pit_mesh_mode": pit_mesh_mode,
        "warning": (
            "Modelo de baja resolución — pit conceptual orientativo, no defensible para ingeniería."
            if is_low_resolution
            else None
        ),
        "input_params": {
            "pit_angle": req.pit_angle,
            "bench_height": req.bench_height,
            "berm_width": req.berm_width,
            "price": req.price,
            "mining_cost": req.mining_cost,
            "processing_cost": req.processing_cost,
            "recovery": req.recovery,
        },
        **ref_metadata,
        **extended_metadata,
    }
