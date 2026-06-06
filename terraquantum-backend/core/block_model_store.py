import json
import os
import re
import zipfile
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from core.config import (
    BASE_DIR,
    DATA_DIR,
    DEFAULT_BLOCK_MODEL_FILENAME,
    DEFAULT_BLOCK_MODEL_PATH,
    PROJECTS_DIR,
    RUN_ANOMALY_FILENAME,
    RUN_BLOCK_MODEL_FILENAME,
    RUN_FOCUSING_FILENAME,
    TMP_DIR,
)
from core.logging import get_logger

_log = get_logger(__name__)


TRACE_ID_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,127}$")
RUN_INPUTS_FILENAME = "inputs.json"
TERRAIN_METADATA_FILENAME = "terrain_metadata.json"
TERRAIN_DEM_MATRIX_FILENAME = "terrain_dem_matrix.json"
RUN_OBSERVATIONS_FILENAME = "observations.json"
RUN_REPORT_FILENAME = "report.json"
RUN_FAVORABILITY_FILENAME = "favorability.json"
RUN_METRICS_FILENAME = "metrics.json"
RUN_SCHEDULE_FILENAME = "schedule.json"
RUN_SOURCE_GRAVITY_FILENAME = "source_gravity.csv"
RUN_GRAVITY_IMPORT_METADATA_FILENAME = "gravity_import_metadata.json"
PROJECT_META_FILENAME = "project_meta.json"

RUN_VTK_FILENAME = "block_model_core.vtr"   # FASE 10: Exportación VTK industrial
RUN_MANIFEST_FILENAME = "run_manifest.json"  # HITO 2: Provenance audit trail
RUN_JOINT_BLOCK_MODEL_FILENAME = "block_model_joint.parquet"        # HITO 1: schema joint v3.0
RUN_MAGNETIC_BLOCK_MODEL_FILENAME = "block_model_magnetic.parquet"  # HITO 1: schema magnetic v3.0

RUN_EXPORT_FILENAMES = (
    RUN_BLOCK_MODEL_FILENAME,
    RUN_ANOMALY_FILENAME,
    RUN_FOCUSING_FILENAME,
    RUN_INPUTS_FILENAME,
    RUN_OBSERVATIONS_FILENAME,
    RUN_REPORT_FILENAME,
    RUN_FAVORABILITY_FILENAME,
    RUN_METRICS_FILENAME,
    RUN_SCHEDULE_FILENAME,
    RUN_SOURCE_GRAVITY_FILENAME,
    RUN_GRAVITY_IMPORT_METADATA_FILENAME,
    RUN_VTK_FILENAME,
    RUN_MANIFEST_FILENAME,
    RUN_JOINT_BLOCK_MODEL_FILENAME,
    RUN_MAGNETIC_BLOCK_MODEL_FILENAME,
)


@dataclass(frozen=True)
class BlockModelReference:
    path: Path
    project_id: Optional[str] = None
    run_id: Optional[str] = None
    is_legacy: bool = True

    def metadata(self):
        return {
            "projectId": self.project_id,
            "runId": self.run_id,
            "blockModelPath": str(self.path),
            "storageMode": "legacy" if self.is_legacy else "project_run",
        }


def clean_trace_id(value: Optional[str], field_name: str) -> Optional[str]:
    if value is None:
        return None

    clean_value = str(value).strip()
    if clean_value == "":
        return None

    if clean_value in {".", ".."} or not TRACE_ID_PATTERN.match(clean_value):
        raise ValueError(
            f"{field_name} invalido. Use letras, numeros, guion, punto o underscore."
        )

    return clean_value


def clean_trace_context(
    project_id: Optional[str] = None,
    run_id: Optional[str] = None,
):
    clean_project_id = clean_trace_id(project_id, "project_id")
    clean_run_id = clean_trace_id(run_id, "run_id")

    if bool(clean_project_id) != bool(clean_run_id):
        raise ValueError("project_id y run_id deben enviarse juntos.")

    return clean_project_id, clean_run_id


def get_run_dir(project_id: str, run_id: str) -> Path:
    clean_project_id, clean_run_id = clean_trace_context(project_id, run_id)
    if not clean_project_id or not clean_run_id:
        raise ValueError("project_id y run_id son requeridos.")
    return PROJECTS_DIR / clean_project_id / "runs" / clean_run_id


def get_project_meta_path(project_id: str) -> Path:
    clean_project_id = clean_trace_id(project_id, "project_id")

    if not clean_project_id:
        raise ValueError("project_id es requerido.")

    return PROJECTS_DIR / clean_project_id / PROJECT_META_FILENAME


def save_project_meta(project_id: str, meta: dict) -> None:
    meta_path = get_project_meta_path(project_id)
    project_dir = meta_path.parent
    project_dir.mkdir(parents=True, exist_ok=True)

    tmp_path = meta_path.with_suffix(".tmp")
    tmp_path.write_text(
        json.dumps(meta, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    tmp_path.replace(meta_path)


def load_project_meta(project_id: str) -> Optional[dict]:
    try:
        meta_path = get_project_meta_path(project_id)

        if not meta_path.exists():
            return None

        return json.loads(meta_path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return None
    except json.JSONDecodeError as exc:
        _log.warning("project_meta_corrupted", project_id=project_id, error=str(exc))
        return None
    except Exception as exc:
        _log.error("project_meta_load_error", project_id=project_id, error=str(exc))
        return None


def get_run_source_gravity_csv_path(project_id: str, run_id: str) -> Path:
    return get_run_dir(project_id, run_id) / "source_gravity.csv"


def get_run_gravity_import_metadata_path(project_id: str, run_id: str) -> Path:
    return get_run_dir(project_id, run_id) / "gravity_import_metadata.json"


def get_run_block_model_reference(
    project_id: Optional[str] = None,
    run_id: Optional[str] = None,
    filename: str = RUN_BLOCK_MODEL_FILENAME,
) -> BlockModelReference:
    clean_project_id, clean_run_id = clean_trace_context(project_id, run_id)

    if not clean_project_id or not clean_run_id:
        return BlockModelReference(path=DEFAULT_BLOCK_MODEL_PATH)

    clean_filename = Path(str(filename or RUN_BLOCK_MODEL_FILENAME)).name
    if clean_filename in {"", ".", ".."}:
        clean_filename = RUN_BLOCK_MODEL_FILENAME

    return BlockModelReference(
        path=get_run_dir(clean_project_id, clean_run_id) / clean_filename,
        project_id=clean_project_id,
        run_id=clean_run_id,
        is_legacy=False,
    )


def get_run_anomaly_reference(
    project_id: Optional[str] = None,
    run_id: Optional[str] = None,
) -> BlockModelReference:
    return get_run_block_model_reference(
        project_id=project_id,
        run_id=run_id,
        filename=RUN_ANOMALY_FILENAME,
    )


def get_run_focusing_reference(
    project_id: Optional[str] = None,
    run_id: Optional[str] = None,
) -> BlockModelReference:
    """Referencia al parquet de focusing MS-x. Solo existe cuando enable_focusing=True."""
    return get_run_block_model_reference(
        project_id=project_id,
        run_id=run_id,
        filename=RUN_FOCUSING_FILENAME,
    )


def get_run_metadata_path(
    project_id: Optional[str] = None,
    run_id: Optional[str] = None,
    filename: str = "",
) -> Optional[Path]:
    clean_project_id, clean_run_id = clean_trace_context(project_id, run_id)

    if not clean_project_id or not clean_run_id:
        return None

    clean_filename = Path(str(filename)).name
    if clean_filename in {"", ".", ".."}:
        raise ValueError("filename invalido para metadata de run.")

    return get_run_dir(clean_project_id, clean_run_id) / clean_filename


def get_run_inputs_path(
    project_id: Optional[str] = None,
    run_id: Optional[str] = None,
) -> Optional[Path]:
    return get_run_metadata_path(
        project_id=project_id,
        run_id=run_id,
        filename=RUN_INPUTS_FILENAME,
    )


def get_run_observations_path(
    project_id: Optional[str] = None,
    run_id: Optional[str] = None,
) -> Optional[Path]:
    return get_run_metadata_path(
        project_id=project_id,
        run_id=run_id,
        filename=RUN_OBSERVATIONS_FILENAME,
    )


def get_run_report_path(
    project_id: Optional[str] = None,
    run_id: Optional[str] = None,
) -> Optional[Path]:
    return get_run_metadata_path(
        project_id=project_id,
        run_id=run_id,
        filename=RUN_REPORT_FILENAME,
    )


def get_run_favorability_path(
    project_id: Optional[str] = None,
    run_id: Optional[str] = None,
) -> Optional[Path]:
    return get_run_metadata_path(
        project_id=project_id,
        run_id=run_id,
        filename=RUN_FAVORABILITY_FILENAME,
    )


def get_run_metrics_path(
    project_id: Optional[str] = None,
    run_id: Optional[str] = None,
) -> Optional[Path]:
    return get_run_metadata_path(
        project_id=project_id,
        run_id=run_id,
        filename=RUN_METRICS_FILENAME,
    )


def get_run_schedule_path(
    project_id: Optional[str] = None,
    run_id: Optional[str] = None,
) -> Optional[Path]:
    return get_run_metadata_path(
        project_id=project_id,
        run_id=run_id,
        filename=RUN_SCHEDULE_FILENAME,
    )


def get_run_files_status(run_dir: Path) -> dict:
    return {
        "block_model": (run_dir / RUN_BLOCK_MODEL_FILENAME).exists(),
        "block_model_anomaly": (run_dir / RUN_ANOMALY_FILENAME).exists(),
        "block_model_focusing": (run_dir / RUN_FOCUSING_FILENAME).exists(),
        "block_model_magnetic": (run_dir / RUN_MAGNETIC_BLOCK_MODEL_FILENAME).exists(),
        "block_model_joint": (run_dir / RUN_JOINT_BLOCK_MODEL_FILENAME).exists(),
        "inputs": (run_dir / RUN_INPUTS_FILENAME).exists(),
        "observations": (run_dir / RUN_OBSERVATIONS_FILENAME).exists(),
        "report": (run_dir / RUN_REPORT_FILENAME).exists(),
        "favorability": (run_dir / RUN_FAVORABILITY_FILENAME).exists(),
        "metrics": (run_dir / RUN_METRICS_FILENAME).exists(),
        "schedule": (run_dir / RUN_SCHEDULE_FILENAME).exists(),
        "source_gravity": (run_dir / RUN_SOURCE_GRAVITY_FILENAME).exists(),
        "gravity_import_metadata": (run_dir / RUN_GRAVITY_IMPORT_METADATA_FILENAME).exists(),
        "run_manifest": (run_dir / RUN_MANIFEST_FILENAME).exists(),
    }


def read_run_json(run_dir: Path, filename: str, field_name: str, read_errors: dict):
    path = run_dir / filename

    if not path.exists():
        return None

    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:
        read_errors[field_name] = str(exc)
        return None


def list_project_runs() -> dict:
    if not PROJECTS_DIR.exists():
        return {
            "totalProjects": 0,
            "totalRuns": 0,
            "projects": [],
        }

    projects = []
    total_runs = 0

    for project_dir in sorted(PROJECTS_DIR.iterdir(), key=lambda path: path.name):
        if not project_dir.is_dir():
            continue

        runs_dir = project_dir / "runs"
        runs = []

        if runs_dir.exists():
            for run_dir in sorted(runs_dir.iterdir(), key=lambda path: path.name):
                if not run_dir.is_dir():
                    continue

                runs.append(
                    {
                        "runId": run_dir.name,
                        "runPath": str(run_dir),
                        "exists": run_dir.exists(),
                        "files": get_run_files_status(run_dir),
                    }
                )

        total_runs += len(runs)
        projects.append(
            {
                "projectId": project_dir.name,
                "projectMeta": load_project_meta(project_dir.name),
                "runs": runs,
            }
        )

    return {
        "totalProjects": len(projects),
        "totalRuns": total_runs,
        "projects": projects,
    }


def get_project_run_detail(project_id: str, run_id: str) -> dict:
    clean_project_id, clean_run_id = clean_trace_context(project_id, run_id)

    if not clean_project_id or not clean_run_id:
        raise ValueError("project_id y run_id son requeridos.")

    run_dir = get_run_dir(clean_project_id, clean_run_id)
    read_errors = {}

    return {
        "projectId": clean_project_id,
        "runId": clean_run_id,
        "runPath": str(run_dir),
        "exists": run_dir.exists(),
        "files": get_run_files_status(run_dir),
        "inputs": read_run_json(run_dir, RUN_INPUTS_FILENAME, "inputs", read_errors),
        "observations": read_run_json(
            run_dir,
            RUN_OBSERVATIONS_FILENAME,
            "observations",
            read_errors,
        ),
        "report": read_run_json(run_dir, RUN_REPORT_FILENAME, "report", read_errors),
        "favorability": read_run_json(
            run_dir,
            RUN_FAVORABILITY_FILENAME,
            "favorability",
            read_errors,
        ),
        "metrics": read_run_json(run_dir, RUN_METRICS_FILENAME, "metrics", read_errors),
        "schedule": read_run_json(run_dir, RUN_SCHEDULE_FILENAME, "schedule", read_errors),
        "gravityImportMetadata": read_run_json(
            run_dir,
            RUN_GRAVITY_IMPORT_METADATA_FILENAME,
            "gravityImportMetadata",
            read_errors,
        ),
        "sourceGravityExists": (run_dir / RUN_SOURCE_GRAVITY_FILENAME).exists(),
        "sourceGravityPath": str(run_dir / RUN_SOURCE_GRAVITY_FILENAME) if (run_dir / RUN_SOURCE_GRAVITY_FILENAME).exists() else None,
        "focusingExists": (run_dir / RUN_FOCUSING_FILENAME).exists(),
        "focusingPath": str(run_dir / RUN_FOCUSING_FILENAME) if (run_dir / RUN_FOCUSING_FILENAME).exists() else None,
        "readErrors": read_errors,
    }


def read_numeric_field(data, field_name: str):
    if not isinstance(data, dict):
        return None

    value = data.get(field_name)
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return float(value)

    return None


def numeric_delta(base_value, compare_value):
    if base_value is None or compare_value is None:
        return None

    return compare_value - base_value


def summarize_run_for_compare(detail: dict) -> dict:
    return {
        "projectId": detail.get("projectId"),
        "runId": detail.get("runId"),
        "exists": detail.get("exists"),
        "metrics": detail.get("metrics"),
        "report": detail.get("report"),
    }


def compare_project_runs(
    base_project_id: str,
    base_run_id: str,
    compare_project_id: str,
    compare_run_id: str,
) -> dict:
    base_detail = get_project_run_detail(base_project_id, base_run_id)
    compare_detail = get_project_run_detail(compare_project_id, compare_run_id)

    base_metrics = base_detail.get("metrics")
    compare_metrics = compare_detail.get("metrics")
    base_report = base_detail.get("report")
    compare_report = compare_detail.get("report")

    return {
        "baseRun": summarize_run_for_compare(base_detail),
        "compareRun": summarize_run_for_compare(compare_detail),
        "deltas": {
            "npv_delta": numeric_delta(
                read_numeric_field(base_metrics, "npv"),
                read_numeric_field(compare_metrics, "npv"),
            ),
            "tonnage_delta": numeric_delta(
                read_numeric_field(base_metrics, "tonnage"),
                read_numeric_field(compare_metrics, "tonnage"),
            ),
            "avg_grade_delta": numeric_delta(
                read_numeric_field(base_metrics, "avg_grade"),
                read_numeric_field(compare_metrics, "avg_grade"),
            ),
            "lom_years_delta": numeric_delta(
                read_numeric_field(base_metrics, "lom_years"),
                read_numeric_field(compare_metrics, "lom_years"),
            ),
            "estimated_total_tonnage_delta": numeric_delta(
                read_numeric_field(base_report, "estimated_total_tonnage"),
                read_numeric_field(compare_report, "estimated_total_tonnage"),
            ),
            "avg_geophysics_grade_delta": numeric_delta(
                read_numeric_field(base_report, "avg_grade"),
                read_numeric_field(compare_report, "avg_grade"),
            ),
            "max_probability_delta": numeric_delta(
                read_numeric_field(base_report, "max_probability"),
                read_numeric_field(compare_report, "max_probability"),
            ),
        },
    }


def export_project_run_zip(project_id: str, run_id: str) -> Path:
    clean_project_id, clean_run_id = clean_trace_context(project_id, run_id)

    if not clean_project_id or not clean_run_id:
        raise ValueError("project_id y run_id son requeridos.")

    run_dir = get_run_dir(clean_project_id, clean_run_id)
    if not run_dir.exists() or not run_dir.is_dir():
        raise ValueError(
            f"No existe la corrida project_id={clean_project_id}, run_id={clean_run_id}."
        )

    export_dir = TMP_DIR / "exports"
    export_dir.mkdir(parents=True, exist_ok=True)
    zip_path = export_dir / f"project_{clean_project_id}__run_{clean_run_id}.zip"

    with zipfile.ZipFile(zip_path, mode="w", compression=zipfile.ZIP_DEFLATED) as zf:
        for filename in RUN_EXPORT_FILENAMES:
            path = run_dir / filename
            if path.exists() and path.is_file():
                zf.write(path, arcname=filename)

    return zip_path


def resolve_block_model_reference(
    file_name: Optional[str] = None,
    project_id: Optional[str] = None,
    run_id: Optional[str] = None,
) -> BlockModelReference:
    clean_project_id, clean_run_id = clean_trace_context(project_id, run_id)

    if clean_project_id and clean_run_id:
        filename = Path(str(file_name or RUN_BLOCK_MODEL_FILENAME)).name
        if filename == DEFAULT_BLOCK_MODEL_FILENAME:
            filename = RUN_BLOCK_MODEL_FILENAME
        return get_run_block_model_reference(clean_project_id, clean_run_id, filename)

    raw = str(file_name or DEFAULT_BLOCK_MODEL_FILENAME).strip()
    candidate = Path(raw)

    possible_paths = []

    if candidate.is_absolute():
        possible_paths.append(candidate)
    else:
        possible_paths.append(DATA_DIR / raw)
        possible_paths.append(DATA_DIR / candidate.name)
        possible_paths.append(BASE_DIR / raw)

    for path in possible_paths:
        if path.exists():
            return BlockModelReference(path=path)

    return BlockModelReference(path=possible_paths[-1])


# ─── Terrain persistence helpers ─────────────────────────────────────────────

def get_terrain_metadata_path(project_id: str) -> Path:
    clean_project_id = clean_trace_id(project_id, "project_id")
    if not clean_project_id:
        raise ValueError("project_id es requerido.")
    return PROJECTS_DIR / clean_project_id / TERRAIN_METADATA_FILENAME


def get_terrain_dem_matrix_path(project_id: str) -> Path:
    clean_project_id = clean_trace_id(project_id, "project_id")
    if not clean_project_id:
        raise ValueError("project_id es requerido.")
    return PROJECTS_DIR / clean_project_id / TERRAIN_DEM_MATRIX_FILENAME


def save_terrain_metadata(project_id: str, metadata: dict) -> Path:
    path = get_terrain_metadata_path(project_id)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = path.with_suffix(".tmp")
    tmp_path.write_text(
        json.dumps(metadata, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    tmp_path.replace(path)
    return path


def load_terrain_metadata(project_id: str) -> Optional[dict]:
    try:
        path = get_terrain_metadata_path(project_id)
        if not path.exists():
            return None
        return json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return None
    except json.JSONDecodeError as exc:
        _log.warning("terrain_metadata_corrupted", project_id=project_id, error=str(exc))
        return None
    except Exception as exc:
        _log.error("terrain_metadata_load_error", project_id=project_id, error=str(exc))
        return None


def save_terrain_dem_matrix(
    project_id: str,
    dem_matrix: list,
) -> Path:
    path = get_terrain_dem_matrix_path(project_id)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = path.with_suffix(".tmp")
    tmp_path.write_text(
        json.dumps(dem_matrix, ensure_ascii=False),
        encoding="utf-8",
    )
    tmp_path.replace(path)
    return path


def load_terrain_dem_matrix(project_id: str) -> Optional[list]:
    try:
        path = get_terrain_dem_matrix_path(project_id)
        if not path.exists():
            return None
        return json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return None
    except json.JSONDecodeError as exc:
        _log.warning("terrain_dem_matrix_corrupted", project_id=project_id, error=str(exc))
        return None
    except Exception as exc:
        _log.error("terrain_dem_matrix_load_error", project_id=project_id, error=str(exc))
        return None


def update_run_status(
    project_id: str,
    run_id: str,
    status: str,
    progress: float,
    stage: str,
    message: str,
    metrics: Optional[dict] = None,
    error: Optional[str] = None,
) -> None:
    """Escribe el estado de la inversión en schedule.json con Atomic Write.

    Patrón: escribe a .tmp → fsync → os.replace (sin corrupción de JSON).
    Si project_id/run_id no son válidos, retorna silenciosamente.
    """
    path = get_run_schedule_path(project_id, run_id)
    if path is None:
        return

    path.parent.mkdir(parents=True, exist_ok=True)

    payload = {
        "project_id": project_id,
        "run_id": run_id,
        "status": status,
        "progress": round(float(progress), 3),
        "stage": stage,
        "message": message,
        "heartbeat_at": datetime.now(timezone.utc).isoformat(),
        "metrics": metrics,
        "error": error,
    }

    tmp_path = path.with_suffix(".tmp")
    with tmp_path.open("w", encoding="utf-8") as f:
        json.dump(payload, f, indent=2, ensure_ascii=False)
        f.flush()
        os.fsync(f.fileno())

    os.replace(str(tmp_path), str(path))


_PARQUET_SCHEMA_VERSION = "v3.0"

_REQUIRED_COLUMNS_ALL = {"run_type", "schema_version"}

_REQUIRED_COLUMNS_BY_RUN_TYPE = {
    "gravity": {"x", "y", "z", "density"},
    "magnetic": {"x_m", "y_m", "z_m", "susceptibility_si"},
    "joint": {"x_m", "y_m", "z_m", "density_t_m3", "susceptibility_si"},
}

_VALID_RUN_TYPES = frozenset(_REQUIRED_COLUMNS_BY_RUN_TYPE.keys())


def validate_parquet_schema(path: Path, expected_run_type: Optional[str] = None) -> dict:
    """Valida que un Parquet cumple el contrato de schema v3.0.

    Retorna un dict con ``valid`` (bool), ``run_type`` leído del archivo,
    ``schema_version`` leído, y ``errors`` (lista de strings vacía si todo OK).

    No lanza excepciones — el llamador decide qué hacer con ``valid=False``.
    """
    errors = []

    try:
        import polars as pl
        df = pl.read_parquet(str(path), n_rows=1)
    except Exception as exc:
        return {"valid": False, "run_type": None, "schema_version": None, "errors": [f"read_error: {exc}"]}

    columns = set(df.columns)

    missing_required = _REQUIRED_COLUMNS_ALL - columns
    if missing_required:
        errors.append(f"missing_columns: {sorted(missing_required)}")

    run_type_val = None
    schema_version_val = None

    if "run_type" in columns:
        try:
            run_type_val = df["run_type"][0]
        except Exception:
            pass

    if "schema_version" in columns:
        try:
            schema_version_val = df["schema_version"][0]
        except Exception:
            pass

    if schema_version_val and schema_version_val != _PARQUET_SCHEMA_VERSION:
        errors.append(f"schema_version_mismatch: got={schema_version_val}, expected={_PARQUET_SCHEMA_VERSION}")

    if run_type_val and run_type_val not in _VALID_RUN_TYPES:
        errors.append(f"invalid_run_type: {run_type_val}")

    effective_run_type = expected_run_type or run_type_val
    if effective_run_type in _REQUIRED_COLUMNS_BY_RUN_TYPE:
        missing_typed = _REQUIRED_COLUMNS_BY_RUN_TYPE[effective_run_type] - columns
        if missing_typed:
            errors.append(f"missing_{effective_run_type}_columns: {sorted(missing_typed)}")

    return {
        "valid": len(errors) == 0,
        "run_type": run_type_val,
        "schema_version": schema_version_val,
        "errors": errors,
    }


def sha256_file(path: Path) -> str:
    """SHA-256 hex digest de un archivo en disco. Lectura en chunks para archivos grandes."""
    import hashlib
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def write_run_manifest(run_dir: Path, manifest: dict) -> Path:
    """Escribe run_manifest.json de forma atómica (write tmp → os.replace).

    Si el write falla el caller debe capturar la excepción — el manifest es
    adición non-fatal y no debe bloquear el resultado de la inversión.
    """
    path = run_dir / RUN_MANIFEST_FILENAME
    run_dir.mkdir(parents=True, exist_ok=True)
    tmp_path = path.with_suffix(".tmp")
    tmp_path.write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2, default=str),
        encoding="utf-8",
    )
    tmp_path.replace(path)
    return path


def resolve_mine_design_block_model_reference(
    file_name: Optional[str] = None,
    project_id: Optional[str] = None,
    run_id: Optional[str] = None,
) -> BlockModelReference:
    clean_project_id, clean_run_id = clean_trace_context(project_id, run_id)

    if clean_project_id and clean_run_id:
        filename = Path(str(file_name or RUN_BLOCK_MODEL_FILENAME)).name
        if filename == DEFAULT_BLOCK_MODEL_FILENAME:
            filename = RUN_BLOCK_MODEL_FILENAME
        return get_run_block_model_reference(clean_project_id, clean_run_id, filename)

    if not file_name:
        raise ValueError(
            "Debe proveer project_id/run_id o file explícito. No existe fallback silencioso a modelo legacy."
        )

    raw = str(file_name).strip()
    if not raw:
        raise ValueError(
            "Debe proveer project_id/run_id o file explícito. No existe fallback silencioso a modelo legacy."
        )
    candidate = Path(raw)

    possible_paths = []

    if candidate.is_absolute():
        possible_paths.append(candidate)
    else:
        possible_paths.append(BASE_DIR / raw)
        possible_paths.append(BASE_DIR / candidate.name)
        possible_paths.append(DATA_DIR / raw)
        possible_paths.append(DATA_DIR / candidate.name)

    for path in possible_paths:
        if path.exists():
            return BlockModelReference(path=path)

    return BlockModelReference(path=possible_paths[-1])
