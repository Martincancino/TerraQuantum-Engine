import json
import os
import uuid
from concurrent.futures import ProcessPoolExecutor, as_completed

import numpy as np
import polars as pl

from engine import LerchsGrossmannEngine
from core.block_model_store import resolve_block_model_reference
from core.config import TMP_DIR, ensure_runtime_dirs
from schemas.scenario_sweep_schema import SweepRequest
from services.block_model_service import ensure_visual_columns, get_index_columns


def evaluate_price(p, grade, tonnage, domain, resource_class, req_dict, nx, ny, nz):
    if req_dict["exclude_inferred"]:
        grade = np.where(resource_class == 3, 0.0, grade)

    pit_exit_x = (nx * req_dict["block_size_x"]) / 2.0
    pit_exit_z = (nz * req_dict["block_size_z"]) / 2.0

    x_grid_3d, y_grid_3d, z_grid_3d = np.mgrid[0:nx, 0:ny, 0:nz]

    dist_horiz = np.sqrt(
        ((x_grid_3d * req_dict["block_size_x"]) - pit_exit_x) ** 2
        + ((z_grid_3d * req_dict["block_size_z"]) - pit_exit_z) ** 2
    )

    dist_vert_ramp = (y_grid_3d * req_dict["block_size_y"]) / req_dict[
        "ramp_gradient"
    ]

    total_haul_dist = dist_horiz + dist_vert_ramp

    costo_mina_real_3d = req_dict["mining_cost"] + (
        total_haul_dist * req_dict["haulage_cost_per_m"]
    )

    costo_mina_real_1d = costo_mina_real_3d.flatten(order="F")

    ingresos = tonnage * (grade / 100.0) * req_dict["recovery"] * p

    costos = (tonnage * costo_mina_real_1d) + (
        tonnage * req_dict["processing_cost"] * (domain > 0)
    )

    profit_1d = ingresos - costos
    profit_3d = profit_1d.reshape((nx, ny, nz), order="F")

    domain_3d = domain.reshape((nx, ny, nz), order="F")

    angle_matrix = np.where(
        domain_3d == 1,
        38.0,
        req_dict["pit_angle"],
    ).astype(np.float32)

    engine = LerchsGrossmannEngine(
        profit_3d,
        req_dict["block_size_x"],
        req_dict["block_size_y"],
        req_dict["block_size_z"],
        angle_matrix,
    )

    mined_mask, _ = engine.optimize_with_maxflow()

    mask_1d = mined_mask.flatten(order="F")

    npv = float(np.dot(profit_1d, mask_1d))
    ton = float(np.sum(tonnage[mask_1d]))

    return {
        "price": float(p),
        "npv": npv,
        "tonnage": ton,
    }


def run_scenario_sweep(req: SweepRequest):
    print("[SCENARIO-SWEEP-SERVICE] Iniciando análisis de sensibilidad.")

    ensure_runtime_dirs()

    job_id = str(uuid.uuid4())

    try:
        block_model_ref = resolve_block_model_reference(
            file_name=req.file,
            project_id=req.project_id,
            run_id=req.run_id,
        )
    except ValueError as exc:
        return {
            "status": "error",
            "detail": str(exc),
        }

    file_path = str(block_model_ref.path)

    if not os.path.exists(file_path):
        return {
            "status": "error",
            "detail": f"No existe el archivo de block model: {req.file}",
        }

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

    grade = df["grade"].to_numpy()
    tonnage = df["tonnage"].to_numpy()
    domain = df["domain"].to_numpy()

    if "resource_class" in df.columns:
        resource_class = df["resource_class"].to_numpy()
    else:
        resource_class = np.ones_like(grade, dtype=np.int8)

    steps = max(1, int(req.steps))
    prices = np.linspace(req.price_min, req.price_max, steps)

    results = []
    progress_path = TMP_DIR / f"sweep_{job_id}.json"

    req_dict = req.model_dump()
    max_workers = max(1, (os.cpu_count() or 2) - 1)

    with open(progress_path, "w") as f:
        json.dump(
            {
                "completed": 0,
                "total": len(prices),
                "partial_curve": [],
            },
            f,
        )

    with ProcessPoolExecutor(max_workers=max_workers) as executor:
        futures = [
            executor.submit(
                evaluate_price,
                p,
                grade,
                tonnage,
                domain,
                resource_class,
                req_dict,
                nx,
                ny,
                nz,
            )
            for p in prices
        ]

        completed = 0

        for future in as_completed(futures):
            results.append(future.result())
            completed += 1

            with open(progress_path, "w") as f:
                json.dump(
                    {
                        "completed": completed,
                        "total": len(prices),
                        "partial_curve": results,
                    },
                    f,
                )

    print(
        f"[SCENARIO-SWEEP-SERVICE] Sweep terminado. Job={job_id} Escenarios={len(results)}"
    )

    return {
        "jobId": job_id,
        "status": "done",
        "progress": 1.0,
        "curve": sorted(results, key=lambda x: x["price"]),
        **block_model_ref.metadata(),
    }


def get_scenario_progress(job_id: str):
    progress_path = TMP_DIR / f"sweep_{job_id}.json"

    if not progress_path.exists():
        return {
            "status": "processing",
            "progress": 0,
            "partial_curve": [],
        }

    with open(progress_path) as f:
        data = json.load(f)

    total = max(int(data.get("total", 1)), 1)
    completed = int(data.get("completed", 0))

    progress = completed / total

    sorted_curve = sorted(
        data.get("partial_curve", []),
        key=lambda x: x["price"],
    )

    status = "done" if progress >= 1.0 else "processing"

    return {
        "status": status,
        "progress": progress,
        "partial_curve": sorted_curve,
    }
