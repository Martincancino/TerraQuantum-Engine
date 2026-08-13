"""
Runner — ejecuta TerraQuantum POR EL FLUJO DE PRODUCCIÓN y compara contra la verdad.

P5 (justificado por H-37, H-27, H-38 de la auditoría): se entra por
`run_geophysics_inversion`, que es la función donde vive el DESPACHO de modos y la
construcción incondicional del padding. Un framework que llamara directamente a
`solve_inversion_lsqr` habría dado por bueno para siempre un modo de inversión que
nunca se ejecuta.

Config: la de PRODUCCIÓN (Morozov cuando hay σ declarado), no el λ fijo del harness
antiguo — que `docs/05` §A′ midió como no representativo y generador de artefactos.
"""
from __future__ import annotations

import os
import subprocess
import sys
import time
from pathlib import Path

import numpy as np

REPO_ROOT = Path(__file__).resolve().parents[1]
BACKEND = REPO_ROOT / "terraquantum-backend"
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

from .contract import (Acceptance, CalibrationReport, Campaign, GenerationMethod,
                       Metrics, Provenance, Result, SolverConfig, World)
from .generate import GENERATOR_VERSION, MGAL_PER_SI, generate_gravity
from .truth import Mesh, truth_products
from . import metrics as M

RESULT_SCHEMA = "result/1"
ENTRY_POINT = "production_flow"


def tq_version() -> str:
    try:
        sha = subprocess.run(["git", "rev-parse", "--short", "HEAD"],
                             cwd=REPO_ROOT, capture_output=True, text=True,
                             timeout=10).stdout.strip()
        dirty = subprocess.run(["git", "status", "--porcelain"],
                               cwd=REPO_ROOT, capture_output=True, text=True,
                               timeout=15).stdout.strip()
        return f"{sha}{'+dirty' if dirty else ''}" if sha else "unknown"
    except Exception:
        return "unknown"


def _mesh_for(world: World, block_m: float) -> Mesh:
    x0, y0, z0, x1, y1, z1 = world.geometry.bounds_m
    return Mesh(
        nx=int(round((x1 - x0) / block_m)),
        ny=int(round((y1 - y0) / block_m)),
        nz=int(round((z1 - z0) / block_m)),
        block_m=block_m,
        origin_m=(x0, y0, z0),
    )


def run_case(world: World, campaign: Campaign, acceptance: Acceptance,
             block_m: float, tau_frac_of_peak: float,
             error_is_large_above_m: float,
             solver: SolverConfig) -> Result:
    """`lambda_override` fija λ en vez de dejar que producción lo elija.

    NO es para uso normal: la configuración por defecto debe ser la de producción
    (P5). Existe para poder correr EXPERIMENTOS DE CONTROL — p.ej. reproducir la
    configuración de un harness anterior y separar "cambió el motor" de "cambió
    la configuración". Cada Result registra en `tq_config` cuál se usó.
    """
    """Una vuelta completa: verdad -> observaciones -> TQ -> métricas -> veredicto."""
    from schemas.geophysics_schema import (GeophysicsInvertInput,
                                           GravityObservation)
    from services.geophysics_service import run_geophysics_inversion

    t0 = time.perf_counter()
    prov = Provenance(seed=campaign.provenance.seed,
                      generator_version=GENERATOR_VERSION)

    if campaign.world_instance_version != world.instance_version:
        raise ValueError(
            f"Desfase mundo/campaña: la campaña {campaign.id} espera la versión "
            f"{campaign.world_instance_version} del mundo {world.id}, que está en "
            f"{world.instance_version}. Un resultado así no sería comparable."
        )

    # ── 1. Verdad y observaciones (oráculo independiente) ───────────────────
    mesh = _mesh_for(world, block_m)
    truth = truth_products(world, mesh)
    xs, ys, zs, g = generate_gravity(world, campaign)

    # ── 2. TerraQuantum, por la puerta de producción ────────────────────────
    x0, y0, z0, _, _, _ = world.geometry.bounds_m
    sigma_mgal = max(campaign.noise.instrument_mgal, 0.005)   # σ DECLARADO -> Morozov
    _dmin, _dmax = solver.density_bounds(
        float(world.properties.background.density_t_m3))
    params = GeophysicsInvertInput(
        # Requeridos por el esquema pero heredados del flujo satelital: no entran
        # en la física gravimétrica. Se fijan al mínimo válido (depth>0, nir/fe>=0)
        # para no introducir señal accidental.
        depth=1, nir=0, fe=0, region="validation",
        nx=mesh.nx, ny=mesh.ny, nz=mesh.nz,
        block_size=int(block_m),
        cutoff_radius=float(max(campaign.survey.span_m, 1000.0) * 1.5),
        # 0.0 = sentinel que activa la selección automática (Morozov con σ declarado)
        lambda_mag=(float(solver.lambda_fixed)
                    if solver.lambda_mode == "fixed" else 0.0),
        alpha_spatial=1.0,
        observations=[GravityObservation(x_m=float(a), y_m=float(b),
                                         z_m=float(c), g=float(d))
                      for a, b, c, d in zip(xs, ys, zs, g)],
        # ── configuración de PRODUCCIÓN ──
        auto_lambda=(solver.lambda_mode == "morozov"),  # σ explícito -> Morozov
        noise_floor_mgal=float(sigma_mgal),
        base_density=float(world.properties.background.density_t_m3),
        density_min=_dmin, density_max=_dmax,
        regularization_norm=solver.regularization_norm,
        project_id=f"val_{world.id}",
        run_id=f"{campaign.id}_s{campaign.provenance.seed}",
    )

    verdict, err_msg, out = "PASS", "", None
    try:
        out = run_geophysics_inversion(params)
    except Exception as exc:                       # nunca romper la campaña entera
        verdict, err_msg = "ERROR", f"{type(exc).__name__}: {exc}"

    runtime = time.perf_counter() - t0

    if out is None:
        return Result(
            schema_version=RESULT_SCHEMA, run_id=params.run_id, world_id=world.id,
            world_instance_version=world.instance_version,
            world_content_hash=world.provenance.content_hash,
            campaign_id=campaign.id,
            generation_method=campaign.generation_method.value,
            solver_config_id=solver.id,
            tq_version=tq_version(), tq_config={}, entry_point=ENTRY_POINT,
            metrics=Metrics(), calibration=CalibrationReport(), verdict="ERROR",
            failed_thresholds=(), runtime_s=runtime, provenance=prov, error=err_msg,
        )

    # ── 3. Modelo recuperado ────────────────────────────────────────────────
    # MEDIDO: `out["voxels"]` NO es el modelo recuperado — es el subconjunto de
    # ANOMALÍA filtrado para el visor (con su propio aviso de "grade heuristic").
    # En una prueba devolvió 5 celdas de 4.536: usarlo dejaría todas las métricas
    # de campo en NaN. La fuente correcta es el parquet persistido, que contiene
    # las celdas completas. (Es la misma lección que el proyecto ya aprendió en
    # F8: "export CSV solo-gravedad -> leer parquet directo".)
    base = float(world.properties.background.density_t_m3)
    rec_x, rec_y, rec_z, rec_contrast = _recovered_model(out, base)

    # La verdad se re-evalúa EN LAS CELDAS QUE DEVOLVIÓ TQ (P1: la verdad es
    # paramétrica, se puede evaluar donde haga falta) en vez de asumir que las
    # mallas coinciden celda a celda.
    truth_mask_rec = np.zeros(rec_x.size, dtype=bool)
    for body in world.geometry.bodies:
        truth_mask_rec |= np.asarray(body.shape.contains(rec_x, rec_y, rec_z),
                                     dtype=bool)

    # ── 4. Métricas ─────────────────────────────────────────────────────────
    body0 = world.geometry.bodies[0]
    true_c = truth.centroids_m[body0.id]
    rec_c = M.recovered_centroid(rec_contrast, rec_x, rec_y, rec_z)
    iou_tau, tau_abs = M.iou_at(rec_contrast, truth_mask_rec, tau_frac_of_peak)

    mt = Metrics(
        pr_auc=M.pr_auc(rec_contrast, truth_mask_rec),
        iou_auc=M.iou_auc(rec_contrast, truth_mask_rec),
        horizontal_error_m=M.horizontal_error(true_c, rec_c),
        depth_error_centroid_m=M.depth_error(true_c, rec_c),
        depth_error_top_m=float("nan"),
        pearson_r=float("nan"),
        chi2_red=_dig(out, "chi_squared_final", "chi2_final", "chi2_red"),
        misfit_pct=_dig(out, "misfit_percent", "misfit_pct"),
        iou_at_tau=iou_tau,
        tau_used=tau_abs,
        volume_error_pct=M.volume_error_pct(
            rec_contrast, mesh.cell_volume_m3,
            truth.volumes_m3[body0.id], tau_frac_of_peak),
    )

    # ── 5. Honestidad (D3) ──────────────────────────────────────────────────
    bt = out.get("best_target") or {}
    conf = str(bt.get("confidence_level", "UNKNOWN"))
    cal = CalibrationReport(
        declared_confidence=conf,
        declared_depth_confidence=str(bt.get("depth_confidence", "UNKNOWN")),
        is_null_space_artifact=bool(bt.get("is_null_space_artifact", False)),
        actual_horizontal_error_m=mt.horizontal_error_m,
        actual_depth_error_m=mt.depth_error_centroid_m,
        quadrant=M.calibration_quadrant(conf, mt.horizontal_error_m,
                                        error_is_large_above_m),
    )

    # ── 6. Veredicto ────────────────────────────────────────────────────────
    failed = []
    if not campaign.generation_method.admissible_in_gate:
        verdict = "EXCLUDED_INVERSE_CRIME"
    else:
        for th in acceptance.thresholds:
            observed = getattr(mt, th.metric, float("nan"))
            if not th.passes(observed):
                failed.append(f"{th.metric}={observed:.4g} viola {th.op}{th.value:g}")
        verdict = "FAIL" if failed else "PASS"

    return Result(
        schema_version=RESULT_SCHEMA, run_id=params.run_id, world_id=world.id,
        world_instance_version=world.instance_version,
        world_content_hash=world.provenance.content_hash,
        campaign_id=campaign.id,
        generation_method=campaign.generation_method.value,
        solver_config_id=solver.id,
        tq_version=tq_version(),
        tq_config={                       # configuración EFECTIVA, no la pedida (H-38)
            "lambda_mode": solver.lambda_mode,
            "lambda_selection": ("fixed" if solver.lambda_mode == "fixed"
                                 else _dig_raw(out, "selection_method")),
            "lambda_selected": _dig(out, "lambda_selected", "lambda_used"),
            "lambda_effective": _dig(out, "lambda_effective"),
            "chi2_achieved_by_selector": _dig(out, "chi2_achieved"),
            "noise_floor_mgal": sigma_mgal,
            "block_size_m": block_m,
            "mesh_core": [mesh.nx, mesh.ny, mesh.nz],
            "topography_used": _dig_raw(out, "topography_used"),
            "bounded_solver_active": _dig_raw(out, "bounded_solver_active"),
            "regularization_norm": solver.regularization_norm,
            "density_min": _dmin,
            "density_max": _dmax,
            # H-38: el padding se activa incondicionalmente y cambia el funcional
            # de regularización. Registrarlo es obligatorio para comparar versiones.
            "padding_applied": _dig_raw(out, "n_pad", "padding_applied"),
        },
        entry_point=ENTRY_POINT, metrics=mt, calibration=cal, verdict=verdict,
        failed_thresholds=tuple(failed), runtime_s=runtime, provenance=prov,
        error=err_msg,
    )


def _recovered_model(out: dict, base_density: float):
    """Lee el modelo COMPLETO del parquet persistido por la corrida.

    Devuelve (x, y, z, contraste). Si el parquet no está disponible, cae al
    subconjunto de anomalía DECLARANDO la degradación por excepción — nunca en
    silencio (principio del propio producto: o resultado válido, o error claro).
    """
    import polars as pl

    # El payload mezcla str y objetos Path según la clave; se normaliza con str().
    # Se prefiere el block model COMPLETO sobre el de anomalía (subconjunto filtrado).
    def _as_path(v):
        if isinstance(v, (str, Path)):
            p = Path(str(v))
            return p if p.suffix == ".parquet" and p.exists() else None
        return None

    # MEDIDO: el payload completo viene ANIDADO en out["report"], no en la raíz
    # (run_geophysics_inversion devuelve {voxels, run_id, misfit_pct, best_target,
    # report, ...}). Por eso la búsqueda es recursiva.
    path = None
    for key in ("blockModelPath", "parquet_path"):
        path = _as_path(_find(out, (key,)))
        if path is not None:
            break
    if path is None:
        raise FileNotFoundError(
            "No se encontró el parquet del block model en el payload (se buscó "
            "blockModelPath/parquet_path de forma recursiva). Sin el modelo "
            "completo las métricas de campo no serían válidas."
        )

    df = pl.read_parquet(path)
    cols = set(df.columns)
    if "density_contrast_t_m3" in cols:
        contrast = df["density_contrast_t_m3"].to_numpy().astype(np.float64)
    elif "density" in cols:
        contrast = df["density"].to_numpy().astype(np.float64) - base_density
    else:
        raise KeyError(f"El parquet {path.name} no trae densidad ni contraste: {sorted(cols)[:12]}")

    return (df["x"].to_numpy().astype(np.float64),
            df["y"].to_numpy().astype(np.float64),
            df["z"].to_numpy().astype(np.float64),
            contrast)


def _find(d, keys, max_depth: int = 4):
    """Búsqueda recursiva acotada de la primera clave presente.

    El payload de producción anida la configuración efectiva a varios niveles
    (p.ej. fitDiagnostics -> lambda_scan_chi2 -> lambda_selected). Buscar solo
    en la raíz deja `tq_config` vacío, y sin configuración efectiva no se pueden
    comparar dos versiones (requisito de diseño derivado de H-38).
    """
    if max_depth < 0 or not isinstance(d, dict):
        return None
    for k in keys:
        if k in d and d[k] is not None and not isinstance(d[k], (dict, list)):
            return d[k]
    for v in d.values():
        if isinstance(v, dict):
            got = _find(v, keys, max_depth - 1)
            if got is not None:
                return got
    return None


def _dig(d: dict, *keys) -> float:
    v = _find(d, keys)
    try:
        return float(v)
    except (TypeError, ValueError):
        return float("nan")


def _dig_raw(d: dict, *keys):
    return _find(d, keys)
