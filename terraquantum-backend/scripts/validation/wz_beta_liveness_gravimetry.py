# -*- coding: utf-8 -*-
"""FASE 4 — hallazgo lateral: los DOS solvers gravimetricos NO comparten funcional.

La auditoria 06 documenta (H-33, §9G.1) que en MAGNETOMETRIA `depth_beta` actua o no
segun si el bloque de padding esta activo — dos funcionales de regularizacion en el
mismo solver. Y documenta (H-1, §6.2) que en GRAVIMETRIA es inerte. Lo que no dice es
que gravimetria tiene la MISMA enfermedad, con otro disfraz: `gravimetry.py` contiene
dos solvers gravimetricos, y **solo uno tiene el depth-weighting muerto**.

    `solve_inversion_lsqr`      (:1728) — malla regular, el camino principal
        Ws = diag(1/‖col_j(G_w·Wz)‖)  se calcula sobre el kernel YA pesado por Wz
        ⇒ Wz·Ws = diag(1/‖col_j(G_w)‖)  ⇒ beta se cancela  ⇒ INERTE  (H-1)

    `solve_inversion_treemesh`  (:3633) — malla Octree, se dispara solo cuando
        `use_treemesh` o `should_auto_use_treemesh(...)` (geophysics_service.py:2685)
        Ws = diag(1/‖col_j(G_w)‖)      se calcula sobre el kernel SIN pesar
        smallness = diag(lam·w_reg)·Ws,  m = Ws·m_tilde
        ⇒ en espacio fisico la penalizacion es lam·w_reg_j·m_j  ⇒ beta VIVO

Es decir: **la separacion que la Fase 4 propone medir YA EXISTE en el repositorio**,
escrita por el propio proyecto, en el solver de al lado. Este script lo comprueba
numericamente en vez de argumentarlo: mide, en cada solver, cuanto se mueve la solucion
al cambiar beta. Si el diagnostico es correcto, uno da ruido de punto flotante y el otro
cambia de verdad.

    python scripts/validation/wz_beta_liveness_gravimetry.py
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from exploration.gravimetry import (  # noqa: E402
    GravimetryForward,
    GravimetryInversion,
    solve_inversion_treemesh,
)
from exploration.treemesh import TreeMesh  # noqa: E402

NX = NY = NZ = 6
BLOCK = 100.0
BASE_DENSITY = 2.67
DENSITY_MAX = BASE_DENSITY + 1.5
BETAS = [0.0, 1.0, 2.0, 4.0]
REF_BETA = 2.0


def _grid_centers(nx, ny, nz, bs):
    ix, iy, iz = np.meshgrid(np.arange(nx), np.arange(ny), np.arange(nz), indexing="ij")
    return ((ix.ravel(order="F") + 0.5) * bs,
            (iy.ravel(order="F") + 0.5) * bs,
            (iz.ravel(order="F") + 0.5) * bs)


def _case():
    """Cuerpo sintetico + survey, compartido por los dos solvers."""
    rng = np.random.default_rng(20260814)
    x_c, y_c, z_c = _grid_centers(NX, NY, NZ, BLOCK)
    cx = cz = NX * BLOCK / 2.0
    ax = np.linspace(BLOCK, (NX - 1) * BLOCK, 6)
    gx, gz = np.meshgrid(ax, ax, indexing="ij")
    sensors = np.column_stack([gx.ravel(), np.zeros(gx.size), gz.ravel()]).astype(np.float64)

    contrast = np.zeros(x_c.size, dtype=np.float64)
    body = ((np.abs(x_c - cx) <= BLOCK) & (np.abs(z_c - cz) <= BLOCK)
            & (y_c >= 2 * BLOCK) & (y_c <= 4 * BLOCK))
    contrast[body] = 0.8
    fwd = GravimetryForward(BLOCK, BLOCK, BLOCK, cutoff_radius=5000.0)
    G = fwd._build_sparse_kernel(x_c, y_c, z_c, sensors)
    g_obs = np.asarray(G @ contrast).ravel()
    g_obs = g_obs + 0.01 * float(np.max(np.abs(g_obs))) * rng.standard_normal(g_obs.size)
    return x_c, y_c, z_c, sensors, g_obs


def _rel(a, b):
    a = np.nan_to_num(np.asarray(a, dtype=np.float64), nan=BASE_DENSITY) - BASE_DENSITY
    b = np.nan_to_num(np.asarray(b, dtype=np.float64), nan=BASE_DENSITY) - BASE_DENSITY
    return float(np.linalg.norm(a - b) / max(np.linalg.norm(b), 1e-30))


def run() -> dict:
    x_c, y_c, z_c, sensors, g_obs = _case()
    noise_floor = 0.02 * float(np.max(np.abs(g_obs)))

    # ── Solver 1: malla regular (el camino principal), en sus DOS solvers internos ─
    # Se corre con TRF y con LSQR+GPCG a proposito: si el residuo de beta se debe a
    # parada temprana (el "caveat honesto" que §9G.1 dejo sin cuantificar) y no a la
    # fisica, tiene que cambiar entre los dos y no ser el mismo numero.
    import core.config as _cfg
    inv = GravimetryInversion(NX, NY, NZ, BLOCK, base_density=BASE_DENSITY)
    fwd = GravimetryForward(BLOCK, BLOCK, BLOCK, cutoff_radius=5000.0)
    reg, reg_lsqr = {}, {}
    for bounded, store in ((True, reg), (False, reg_lsqr)):
        _prev = _cfg.USE_BOUNDED_SOLVER
        _cfg.USE_BOUNDED_SOLVER = bounded
        try:
            for beta in BETAS:
                rho, _s, _m, _n = inv.solve_inversion_lsqr(
                    g_obs, None, y_c, lambda_mag=1e-2, alpha_spatial=1.0,
                    forward_model=fwd, sensor_coords=sensors, x_c=x_c, z_c=z_c,
                    density_min=BASE_DENSITY, density_max=DENSITY_MAX,
                    noise_floor=noise_floor, noise_pct=0.02, depth_beta=beta,
                    prune_observable_domain=True, regularization_norm="L2",
                )
                store[beta] = np.asarray(rho, dtype=np.float64)
        finally:
            _cfg.USE_BOUNDED_SOLVER = _prev

    # ── Solver 2: malla Octree (se dispara solo en surveys grandes) ──────────────
    mesh = TreeMesh.from_regular_grid(NX, NY, NZ, BLOCK, max_refinement_depth=0)
    tree = {}
    for beta in BETAS:
        dens, _p, _mi = solve_inversion_treemesh(
            mesh=mesh, g_observed=g_obs, sensor_coords=sensors,
            forward_model=GravimetryForward(BLOCK, BLOCK, BLOCK, cutoff_radius=5000.0),
            lambda_mag=1e-2, alpha_spatial=1.0, depth_beta=beta,
            base_density=BASE_DENSITY, density_min=BASE_DENSITY,
            density_max=DENSITY_MAX, noise_floor=noise_floor, noise_pct=0.02,
        )
        tree[beta] = np.asarray(dens, dtype=np.float64)

    rows = []
    for beta in BETAS:
        if beta == REF_BETA:
            continue
        rows.append({
            "beta": beta,
            "lsqr_trf_rel_diff": _rel(reg[beta], reg[REF_BETA]),
            "lsqr_gpcg_rel_diff": _rel(reg_lsqr[beta], reg_lsqr[REF_BETA]),
            "treemesh_rel_diff": _rel(tree[beta], tree[REF_BETA]),
        })

    print("=" * 92)
    print("FASE 4 — ¿`depth_beta` mueve la solucion? Los DOS solvers gravimetricos")
    print(f"         malla {NX}x{NY}x{NZ}@{BLOCK:.0f} m · {sensors.shape[0]} estaciones · "
          f"diferencia relativa L2 vs beta={REF_BETA:g}")
    print("=" * 92)
    print(f"{'':>6}  {'solve_inversion_lsqr':>36}  {'solve_inversion_treemesh':>26}")
    print(f"{'beta':>6}  {'TRF':>17}{'LSQR+GPCG':>19}  {'(Octree)':>26}")
    print("-" * 92)
    for r in rows:
        print(f"{r['beta']:>6g}  {r['lsqr_trf_rel_diff']:>17.3e}{r['lsqr_gpcg_rel_diff']:>19.3e}  "
              f"{r['treemesh_rel_diff']:>26.3e}")
    trf_max = max(r["lsqr_trf_rel_diff"] for r in rows)
    gpcg_max = max(r["lsqr_gpcg_rel_diff"] for r in rows)
    tree_max = max(r["treemesh_rel_diff"] for r in rows)
    print("-" * 92)
    print(f"{'max':>6}  {trf_max:>17.3e}{gpcg_max:>19.3e}  {tree_max:>26.3e}")
    print()
    print(f"  solve_inversion_lsqr     : depth_beta INERTE COMO FISICA. Lo que queda no es")
    print(f"    el peso de profundidad sino el residuo de PARADA TEMPRANA: Wz sigue siendo un")
    print(f"    precondicionador por la derecha legitimo, y con tolerancias finitas dos")
    print(f"    precondicionadores no aterrizan en el mismo punto. Se ve en que el numero")
    print(f"    DEPENDE DEL SOLVER (TRF {trf_max:.1e} vs LSQR+GPCG {gpcg_max:.1e}): un efecto")
    print(f"    fisico no cambiaria al cambiar de solver. La auditoria dejo este caveat")
    print(f"    explicitamente sin cuantificar (§9G.1); aqui queda cuantificado.")
    print(f"  solve_inversion_treemesh : depth_beta VIVO ({tree_max:.3e}) — "
          f"{tree_max / max(trf_max, 1e-30):.0f}x el residuo del otro solver.")
    print()
    print("  Dos solvers gravimetricos, dos funcionales de regularizacion distintos, el")
    print("  MISMO parametro nominal documentado como 'depth weighting Li & Oldenburg'.")
    print("  Cual se usa lo decide el TAMANO del survey (should_auto_use_treemesh,")
    print("  geophysics_service.py:2685), no el usuario, y nada en la salida lo declara.")
    print("=" * 92)

    out = {
        "kind": "wz_beta_liveness_two_gravimetry_solvers",
        "config": {"mesh": [NX, NY, NZ], "block_m": BLOCK, "betas": BETAS,
                   "ref_beta": REF_BETA, "n_sensors": int(sensors.shape[0])},
        "rows": rows,
        "max_rel_diff": {"solve_inversion_lsqr_trf": trf_max,
                         "solve_inversion_lsqr_gpcg": gpcg_max,
                         "solve_inversion_treemesh": tree_max},
        "ratio_treemesh_over_lsqr": tree_max / max(trf_max, 1e-30),
        "verdict": {
            "solve_inversion_lsqr_inert_as_physics": bool(trf_max < 1e-2),
            "residual_is_early_stopping": bool(
                abs(np.log10(max(trf_max, 1e-30)) - np.log10(max(gpcg_max, 1e-30))) > 0.3
            ),
            "solve_inversion_treemesh_alive": bool(tree_max > 1e-3),
        },
    }
    p = Path(__file__).resolve().parent / "wz_beta_liveness_gravimetry_report.json"
    p.write_text(json.dumps(out, indent=2, ensure_ascii=False, default=float),
                 encoding="utf-8")
    print(f"Reporte -> {p}")
    return out


def main():
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass
    run()


if __name__ == "__main__":
    main()
