"""
Persistencia de resultados, indexada por versión de TerraQuantum.

D1: el historial vive FUERA del árbol de código (convención de ASV: "un repositorio
de archivo de benchmarks separado evita saturar el repositorio principal con
resultados"). Aquí se escribe en `TQ_VALIDATION_HOME` o, por defecto, en el
directorio de datos del usuario — nunca dentro del repositorio.
"""
from __future__ import annotations

import json
import os
from pathlib import Path

from .contract import Result


def results_home() -> Path:
    env = os.getenv("TQ_VALIDATION_HOME")
    if env:
        return Path(env)
    base = os.getenv("LOCALAPPDATA") or os.getenv("XDG_DATA_HOME") \
        or str(Path.home() / ".local" / "share")
    return Path(base) / "TerraQuantum" / "validation_results"


def save(result: Result) -> Path:
    """Un fichero por (versión de TQ, mundo, campaña, semilla). Append-only."""
    d = results_home() / result.tq_version
    d.mkdir(parents=True, exist_ok=True)
    path = (d / f"{result.world_id}__{result.campaign_id}"
            f"__{result.solver_config_id}__s{result.provenance.seed}.json")
    path.write_text(json.dumps(result.to_dict(), indent=2, default=str,
                               ensure_ascii=False), encoding="utf-8")
    return path


def load_version(tq_version: str) -> list[dict]:
    d = results_home() / tq_version
    if not d.exists():
        return []
    return [json.loads(p.read_text(encoding="utf-8")) for p in sorted(d.glob("*.json"))]


def list_versions() -> list[str]:
    home = results_home()
    return sorted([p.name for p in home.iterdir() if p.is_dir()]) if home.exists() else []
