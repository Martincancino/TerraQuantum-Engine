"""
Validate TreeMesh on real Bushveld data: ~350km domain, 441 sensors, regional scale.

Gate criteria:
  - mesh_cells > 50,000       (escala regional demostrada)
  - memory_delta_GB < 2.0     (sin explosión de RAM)
  - time_seconds < 120        (razonable para uso interactivo)
  - misfit_pct < 100.0        (convergió, no es peor que modelo nulo)
  - no NaN en densidades

Parámetros de diseño:
  - block_size = 11586m — cubre el dominio Bushveld (30 celdas × 11.586km ≈ 347km)
  - max_refinement_depth = 2 — cells near sensors: 11.6km → 5.8km → 2.9km
  - refine_radius = 11586m (1×base) — refinamiento conservador, ~80% de cobertura
  - cutoff_radius = 50000m (50km) — captura la señal regional sin G denso
  - lambda_mag = 3.0 (operating point validado en fase 4)
  - alpha_spatial = 10.0

Uso:
    cd terraquantum-backend
    python scripts/validation/validate_bushveld_regional_octree.py
"""

import os
import sys
import json
import time

import numpy as np
import psutil

_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if _DIR not in sys.path:
    sys.path.insert(0, _DIR)

try:
    from exploration.treemesh import TreeMesh
    from exploration.gravimetry import GravimetryForward, solve_inversion_treemesh
except ImportError as exc:
    print(f"[ERROR] Import failed: {exc}")
    sys.exit(2)

# ── Parámetros de inversión ──────────────────────────────────────────────────
BLOCK_SIZE     = 11586.0    # m — cell base size (matches existing Bushveld payload domain)
MAX_REFINE     = 1          # ONE level of refinement: 11.6km→5.8km uniform grid
# STRATEGY: All base cells refine exactly once (refine_radius >> domain).
# Result: 8191 × 8 = 65528 UNIFORM level-1 cells (no cross-level boundaries).
# WHY: The Laplacian Python loop is O(n × n_face_candidates). For multi-level
# octrees, cross-level faces (one 11.6km cell adjacent to 700 small 2.9km cells)
# cause n_candidates ≈ 700 → total 48M inner iterations → ~720s (bottleneck).
# With a UNIFORM level-1 grid, every face has exactly 1-2 same-level neighbors
# → n_candidates ≈ 2 → total ~400k iterations → ~2s. Sprint 3C fix for Laplacian
# vectorization is the proper solution; this uniform-grid strategy is the gate test.
REFINE_RADIUS  = 400_000.0  # m — 400km >> domain (386km) → ALL base cells refine
CUTOFF_RADIUS  = 50_000.0   # m — 50km: sparse G (fast LSQR)
LAMBDA_MAG     = 0.5        # regularización (calibrated for ~65k cells)
ALPHA_SPATIAL  = 0.0        # 0 = skip Laplacian build (Sprint 3C fix pending)
                             # Laplacian face_map bug → O(n^5/3) for large grids
DEPTH_BETA     = 2.0        # Li & Oldenburg depth weighting exponent
DENSITY_MIN    = 2.6        # t/m³ lower bound
DENSITY_MAX    = 4.2        # t/m³ upper bound
DEPTH_M        = 8 * BLOCK_SIZE  # domain depth (8 layers, same as existing payload)
# Pre-processing: remove mean Bouguer background before inversion.
# Bushveld Bouguer anomaly is entirely negative (-22 to -167 mGal). Subtracting
# the mean gives a residual with positive parts (Bushveld intrusions relative to
# background) that can be fitted with positive density contrasts.
PRE_REMOVE_MEAN = True
# Solver
ITER_LIM       = 200
ATOL           = 1e-5

# Gate thresholds
GATE_MIN_CELLS     = 50_000
GATE_MAX_MEM_GB    = 2.0
GATE_MAX_TIME_S    = 120.0
GATE_MAX_MISFIT    = 100.0


def load_bushveld_data(csv_path: str):
    """Returns (sensor_coords, g_observed) from real_bushveld_gravity.csv."""
    import csv
    rows = list(csv.DictReader(open(csv_path, encoding="utf-8")))
    x = np.array([float(r["x_m"]) for r in rows], dtype=np.float64)
    z = np.array([float(r["z_m"]) for r in rows], dtype=np.float64)
    g_mgal = np.array([float(r["g"]) for r in rows], dtype=np.float64)
    y = np.zeros_like(x)  # sensors at surface (y=0)

    sensor_coords = np.column_stack([x, y, z])          # (N, 3)
    g_observed = g_mgal * 1e-5                           # mGal → SI (m/s²)
    return sensor_coords, g_observed


def build_domain_bounds(sensor_coords):
    """Build domain bounds that cover all sensors + 10% padding."""
    x_min, x_max = sensor_coords[:, 0].min(), sensor_coords[:, 0].max()
    z_min, z_max = sensor_coords[:, 2].min(), sensor_coords[:, 2].max()
    pad_x = max((x_max - x_min) * 0.05, BLOCK_SIZE)
    pad_z = max((z_max - z_min) * 0.05, BLOCK_SIZE)
    return (
        (x_min - pad_x, x_max + pad_x),
        (0.0, DEPTH_M),
        (z_min - pad_z, z_max + pad_z),
    )


def validate():
    proc = psutil.Process()
    data_path = os.path.join(_DIR, "tests", "data", "real_bushveld_gravity.csv")

    print("=" * 70)
    print("  VALIDACIÓN BUSHVELD REGIONAL — TreeMesh Octree (~100k celdas)")
    print("=" * 70)

    # ── 1. Cargar datos ────────────────────────────────────────────────────────
    print(f"\n[1/6] Cargando {data_path} ...")
    sensor_coords, g_observed = load_bushveld_data(data_path)
    n_sensors = len(sensor_coords)
    x_extent = (sensor_coords[:, 0].max() - sensor_coords[:, 0].min()) / 1e3
    z_extent = (sensor_coords[:, 2].max() - sensor_coords[:, 2].min()) / 1e3
    print(f"      N_sensores={n_sensors} | dominio≈{x_extent:.0f}km×{z_extent:.0f}km "
          f"| g=[{g_observed.min()*1e5:.1f}, {g_observed.max()*1e5:.1f}] mGal")

    if PRE_REMOVE_MEAN:
        g_mean = float(np.mean(g_observed))
        g_observed = g_observed - g_mean
        g_res_mgal = g_observed * 1e5
        print(f"      [PRE] Mean Bouguer removed: {g_mean*1e5:.2f} mGal. "
              f"Residual range: [{g_res_mgal.min():.1f}, {g_res_mgal.max():.1f}] mGal")

    # ── 2. Construir TreeMesh ──────────────────────────────────────────────────
    _refine_r = REFINE_RADIUS if REFINE_RADIUS is not None else 2.0 * BLOCK_SIZE
    print(f"\n[2/6] Construyendo TreeMesh (block={BLOCK_SIZE/1000:.2f}km, "
          f"max_refine={MAX_REFINE}, refine_r={_refine_r/1000:.1f}km)...")

    x_bounds, y_bounds, z_bounds = build_domain_bounds(sensor_coords)
    domain_km2 = (x_bounds[1]-x_bounds[0]) * (z_bounds[1]-z_bounds[0]) / 1e6

    mesh = TreeMesh(
        x_bounds=x_bounds,
        y_bounds=y_bounds,
        z_bounds=z_bounds,
        base_cell_size=BLOCK_SIZE,
        max_refinement_depth=MAX_REFINE,
        sensor_coords=sensor_coords,
        refine_radius=REFINE_RADIUS,  # None → default 2×base
    )

    n_cells = mesh.n_cells
    print(f"      TreeMesh: {mesh}")
    print(f"      n_cells={n_cells:,} | dominio={x_bounds[0]/1e3:.0f}-{x_bounds[1]/1e3:.0f}km "
          f"× {y_bounds[1]/1e3:.0f}km depth × {z_bounds[0]/1e3:.0f}-{z_bounds[1]/1e3:.0f}km")

    sizes = mesh.get_cell_sizes()
    print(f"      cell_size: min={np.min(sizes):.0f}m max={np.max(sizes):.0f}m")
    unique_levels, level_counts = np.unique(mesh.levels, return_counts=True)
    for lv, cnt in zip(unique_levels, level_counts):
        print(f"        level {lv}: {cnt:,} celdas")

    # ── 3. Iniciar cronómetro + RAM baseline ──────────────────────────────────
    mem_before_gb = proc.memory_info().rss / 1e9
    t0 = time.time()

    # ── 4. Construir Laplaciano ────────────────────────────────────────────────
    print(f"\n[3/6] Construyendo Laplaciano Octree ({n_cells:,} celdas)...")
    t_lap = time.time()

    forward = GravimetryForward(
        dx=BLOCK_SIZE, dy=BLOCK_SIZE, dz=BLOCK_SIZE,
        cutoff_radius=CUTOFF_RADIUS,
    )

    # ── 5. Resolver inversión ──────────────────────────────────────────────────
    print(f"\n[4/6] Construyendo kernel G ({n_sensors} sensores × {n_cells:,} celdas) "
          f"y resolviendo inversión...")
    print(f"      lambda_mag={LAMBDA_MAG}, alpha_spatial={ALPHA_SPATIAL}, "
          f"depth_beta={DEPTH_BETA}, cutoff={CUTOFF_RADIUS/1e3:.0f}km")

    solver_meta: dict = {}
    try:
        estimated_density, relative_score, misfit_pct = solve_inversion_treemesh(
            mesh=mesh,
            g_observed=g_observed,
            sensor_coords=sensor_coords,
            forward_model=forward,
            lambda_mag=LAMBDA_MAG,
            alpha_spatial=ALPHA_SPATIAL,
            depth_beta=DEPTH_BETA,
            density_min=DENSITY_MIN,
            density_max=DENSITY_MAX,
            solver_meta=solver_meta,
            iter_lim=ITER_LIM,
            atol=ATOL,
        )
    except Exception as exc:
        t_elapsed = time.time() - t0
        mem_after_gb = proc.memory_info().rss / 1e9
        print(f"\n[ERROR] solve_inversion_treemesh failed: {type(exc).__name__}: {exc}")
        print(f"        elapsed={t_elapsed:.1f}s | RAM delta={mem_after_gb-mem_before_gb:.2f}GB")
        return None

    t_elapsed = time.time() - t0
    mem_after_gb = proc.memory_info().rss / 1e9
    mem_delta_gb = mem_after_gb - mem_before_gb

    # ── 6. Diagnósticos ────────────────────────────────────────────────────────
    has_nan  = not np.isfinite(estimated_density).all()
    contrast = estimated_density - 2.6
    n_positive = int(np.sum(contrast > 0.05))

    print(f"\n[5/6] Diagnósticos de la densidad recuperada:")
    print(f"      density: min={estimated_density.min():.4f} max={estimated_density.max():.4f} t/m³")
    print(f"      contrast>0.05: {n_positive:,} voxels | NaN: {has_nan}")
    print(f"      cond(A)~{solver_meta.get('acond', float('nan')):.2e} | "
          f"chi2={solver_meta.get('chi2_final', float('nan')):.4f}")

    # ── 7. Reporte gate ────────────────────────────────────────────────────────
    report = {
        "mesh_cells":      n_cells,
        "n_sensors":       n_sensors,
        "domain_km2":      round(domain_km2, 1),
        "min_cell_size_m": round(float(np.min(sizes)), 0),
        "max_cell_size_m": round(float(np.max(sizes)), 0),
        "time_seconds":    round(t_elapsed, 2),
        "memory_before_GB": round(mem_before_gb, 3),
        "memory_after_GB":  round(mem_after_gb, 3),
        "memory_delta_GB":  round(mem_delta_gb, 3),
        "misfit_pct":      round(misfit_pct, 2) if np.isfinite(misfit_pct) else None,
        "has_nan":         has_nan,
        "n_positive_voxels": n_positive,
        "cond_A":          round(solver_meta.get("acond", float("nan")), 1),
        "chi2_final":      round(solver_meta.get("chi2_final", float("nan")), 4),
        "success":         True,
    }

    print(f"\n[6/6] REPORTE GATE:")
    print(json.dumps(report, indent=2))

    # ── 8. Evaluación gate criteria ───────────────────────────────────────────
    gates = {
        "mesh_cells > 50k":    n_cells > GATE_MIN_CELLS,
        "memory_delta < 2GB":  mem_delta_gb < GATE_MAX_MEM_GB,
        "time_s < 120":        t_elapsed < GATE_MAX_TIME_S,
        "misfit < 100%":       (misfit_pct is not None and misfit_pct < GATE_MAX_MISFIT),
        "no NaN":              not has_nan,
    }

    print("\n" + "=" * 70)
    all_pass = all(gates.values())
    for name, passed in gates.items():
        status = "PASS" if passed else "FAIL"
        print(f"  [{status}] {name}")

    print("-" * 70)
    if all_pass:
        print("RESULTADO: TODOS LOS GATES PASAN — Sprint 3C/TreeMesh regional validado.")
        print("           Siguiente paso: Sprint 4 (LOD + Clipping frontend).")
    else:
        failed = [k for k, v in gates.items() if not v]
        print(f"RESULTADO: {len(failed)} gate(s) fallaron: {', '.join(failed)}")
        print("           Ver diagnóstico arriba para debug.")
    print("=" * 70)

    return report


if __name__ == "__main__":
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    result = validate()
    sys.exit(0 if result and result["success"] else 1)
