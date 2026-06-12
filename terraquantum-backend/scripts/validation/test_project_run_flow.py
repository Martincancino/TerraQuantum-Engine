import json
import sys
import zipfile
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

PROJECT_ID = "validation_project"
RUN_ID = "validation_run_001"


def fail(message: str):
    print(f"FAIL: {message}")
    sys.exit(1)


def check(condition: bool, message: str):
    if not condition:
        fail(message)
    print(f"OK: {message}")


def build_observations():
    return [
        {"x_m": 5, "y_m": 0, "z_m": 5, "g": 0.00000080},
        {"x_m": 15, "y_m": 0, "z_m": 5, "g": 0.00000090},
        {"x_m": 25, "y_m": 0, "z_m": 5, "g": 0.00000110},
        {"x_m": 35, "y_m": 0, "z_m": 5, "g": 0.00000150},
        {"x_m": 45, "y_m": 0, "z_m": 5, "g": 0.00000145},
        {"x_m": 55, "y_m": 0, "z_m": 5, "g": 0.00000110},
        {"x_m": 65, "y_m": 0, "z_m": 5, "g": 0.00000090},
        {"x_m": 75, "y_m": 0, "z_m": 5, "g": 0.00000080},
        {"x_m": 5, "y_m": 0, "z_m": 35, "g": 0.00000085},
        {"x_m": 15, "y_m": 0, "z_m": 35, "g": 0.00000100},
        {"x_m": 25, "y_m": 0, "z_m": 35, "g": 0.00000135},
        {"x_m": 35, "y_m": 0, "z_m": 35, "g": 0.00000220},
    ]


def main():
    from core.block_model_store import (
        compare_project_runs,
        export_project_run_zip,
        get_project_run_detail,
        list_project_runs,
    )
    from schemas.geophysics_schema import GeophysicsInvertInput
    from services.block_model_service import build_block_model_response
    from services.geophysics_service import run_geophysics_inversion

    run_dir = REPO_ROOT / "data" / "projects" / PROJECT_ID / "runs" / RUN_ID
    block_model_path = run_dir / "block_model.parquet"
    anomaly_path = run_dir / "block_model_anomaly.parquet"
    inputs_path = run_dir / "inputs.json"
    observations_path = run_dir / "observations.json"
    report_path = run_dir / "report.json"
    metrics_path = run_dir / "metrics.json"
    schedule_path = run_dir / "schedule.json"
    legacy_path = REPO_ROOT / "data" / "block_model_001.parquet"

    print("Validating TerraQuantum project_run block model flow")
    print(f"project_id={PROJECT_ID}")
    print(f"run_id={RUN_ID}")

    params = GeophysicsInvertInput(
        project_id=PROJECT_ID,
        run_id=RUN_ID,
        depth=40,
        nir=83,
        fe=79,
        region="norte_chile",
        lat="-22.28",
        lon="-68.89",
        nx=8,
        ny=8,
        nz=8,
        block_size=10,
        cutoff_radius=600,
        lambda_mag=0.00005,
        alpha_spatial=1.5,
        observations=build_observations(),
    )

    geophysics_result = run_geophysics_inversion(params)
    report = geophysics_result.get("report", {})

    check(block_model_path.exists(), f"created {block_model_path}")
    check(anomaly_path.exists(), f"created {anomaly_path}")
    check(inputs_path.exists(), f"created {inputs_path}")
    check(observations_path.exists(), f"created {observations_path}")
    check(report_path.exists(), f"created {report_path}")

    inputs_data = json.loads(inputs_path.read_text(encoding="utf-8"))
    observations_data = json.loads(observations_path.read_text(encoding="utf-8"))
    report_data = json.loads(report_path.read_text(encoding="utf-8"))

    check(inputs_data.get("project_id") == PROJECT_ID, "inputs project_id matches")
    check(inputs_data.get("run_id") == RUN_ID, "inputs run_id matches")
    check(isinstance(observations_data, list), "observations json is a list")
    check(len(observations_data) >= 10, "observations json has at least 10 observations")
    check(report_data.get("storageMode") == "project_run", "report storageMode is project_run")
    check(report_data.get("projectId") == PROJECT_ID, "report projectId matches")
    check(report_data.get("runId") == RUN_ID, "report runId matches")
    check(bool(report_data.get("recommendation")), "report recommendation exists")
    check(
        bool(report_data.get("parquet_path") or report_data.get("blockModelPath")),
        "report parquet path exists",
    )
    check(report.get("storageMode") == "project_run", "geophysics storageMode is project_run")
    check(report.get("projectId") == PROJECT_ID, "geophysics projectId matches")
    check(report.get("runId") == RUN_ID, "geophysics runId matches")

    block_model = build_block_model_response(
        mode="exploration",
        limit=1000,
        project_id=PROJECT_ID,
        run_id=RUN_ID,
    )

    check("error" not in block_model, "block model response has no error")
    check(block_model.get("returnedCells", 0) > 0, "block model returnedCells > 0")
    check(block_model.get("storageMode") == "project_run", "block model storageMode is project_run")

    # Bloque pit design eliminado (2026-06-10): los módulos de diseño de mina
    # y economía fueron retirados del producto (solo modelo 3D geofísico).
    check(legacy_path.exists(), f"legacy block model still exists at {legacy_path}")

    project_runs = list_project_runs()
    project_entry = next(
        (
            project
            for project in project_runs.get("projects", [])
            if project.get("projectId") == PROJECT_ID
        ),
        None,
    )
    check(project_entry is not None, "project runs listing contains validation_project")

    run_entry = next(
        (
            run
            for run in project_entry.get("runs", [])
            if run.get("runId") == RUN_ID
        ),
        None,
    )
    check(run_entry is not None, "project runs listing contains validation_run_001")

    listed_files = run_entry.get("files", {})
    check(listed_files.get("block_model") is True, "listing files.block_model is true")
    check(listed_files.get("inputs") is True, "listing files.inputs is true")
    check(listed_files.get("observations") is True, "listing files.observations is true")
    check(listed_files.get("report") is True, "listing files.report is true")
    check(listed_files.get("metrics") is True, "listing files.metrics is true")
    check(listed_files.get("schedule") is True, "listing files.schedule is true")

    run_detail = get_project_run_detail(PROJECT_ID, RUN_ID)
    detail_files = run_detail.get("files", {})

    check(run_detail.get("exists") is True, "project run detail exists is true")
    check(run_detail.get("inputs") is not None, "project run detail inputs is not null")
    check(
        isinstance(run_detail.get("observations"), list),
        "project run detail observations is a list",
    )
    check(run_detail.get("report") is not None, "project run detail report is not null")
    check(run_detail.get("metrics") is not None, "project run detail metrics is not null")
    check(
        isinstance(run_detail.get("schedule"), list),
        "project run detail schedule is a list",
    )
    check(detail_files.get("block_model") is True, "detail files.block_model is true")
    check(detail_files.get("inputs") is True, "detail files.inputs is true")
    check(detail_files.get("report") is True, "detail files.report is true")
    check(detail_files.get("metrics") is True, "detail files.metrics is true")
    check(detail_files.get("schedule") is True, "detail files.schedule is true")

    run_comparison = compare_project_runs(
        base_project_id=PROJECT_ID,
        base_run_id=RUN_ID,
        compare_project_id=PROJECT_ID,
        compare_run_id=RUN_ID,
    )
    deltas = run_comparison.get("deltas")
    npv_delta = deltas.get("npv_delta") if isinstance(deltas, dict) else None

    check(run_comparison.get("baseRun", {}).get("exists") is True, "compare baseRun exists is true")
    check(
        run_comparison.get("compareRun", {}).get("exists") is True,
        "compare compareRun exists is true",
    )
    check(isinstance(deltas, dict), "compare deltas exists")
    check(
        npv_delta is None or abs(float(npv_delta)) < 1e-9,
        "compare npv_delta is zero or null for same run",
    )

    zip_path = export_project_run_zip(PROJECT_ID, RUN_ID)
    check(zip_path.exists(), f"export zip exists at {zip_path}")
    check(zip_path.suffix == ".zip", "export path has .zip extension")

    with zipfile.ZipFile(zip_path, mode="r") as zf:
        zip_names = set(zf.namelist())

    check("inputs.json" in zip_names, "export zip contains inputs.json")
    check("observations.json" in zip_names, "export zip contains observations.json")
    check("report.json" in zip_names, "export zip contains report.json")
    check("metrics.json" in zip_names, "export zip contains metrics.json")
    check("schedule.json" in zip_names, "export zip contains schedule.json")

    print("PASS")


if __name__ == "__main__":
    try:
        main()
    except SystemExit:
        raise
    except Exception as exc:
        fail(str(exc))
