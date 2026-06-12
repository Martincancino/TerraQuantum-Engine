"""
Tier 1 A1 — FISTA proyectado: bounds petrofísicos reales a cualquier escala.

Criterios del plan:
  1. Equivalencia con TRF (lsq_linear) en problemas chicos: rel_diff < 1%,
     objetivo dentro del 0.1%.
  2. Bounds SIEMPRE respetados (sin clip post-hoc).
  3. Caso crítico: inversión de esfera compacta con no-negatividad estricta
     (density_min=2.6) pasa de misfit ~35% (LSQR+clip) a < 5%.
  4. Monotonía: objetivo(FISTA) <= objetivo(warm start LSQR+clip) siempre.
  5. Runtime acotado en problemas grandes (marcado slow, opt-in).
"""
import io
import os
import shutil
import sys
import uuid
from pathlib import Path

import numpy as np
import pytest
import scipy.sparse as sp
from scipy.optimize import lsq_linear
from scipy.sparse.linalg import lsqr

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, os.path.dirname(__file__))  # para importar el builder del flujo de campo

from exploration.solver_preconditioned import solve_inversion_pgd_fista

RNG = np.random.default_rng(7)


def _random_box_problem(n_rows=600, n=300, density=0.05):
    """Sistema sobredeterminado bien condicionado con solución fuera del box."""
    G = sp.random(n_rows, n, density=density, random_state=7, format="csr")
    # Diagonal dominante para condicionamiento sano (el sistema aumentado real
    # incluye regularización que cumple el mismo rol).
    G = G + sp.vstack([sp.eye(n), sp.csr_matrix((n_rows - n, n))]).tocsr() * 0.5
    x_true = RNG.standard_normal(n) * 2.0          # excede el box a propósito
    d = G @ x_true + RNG.normal(0, 0.01, n_rows)
    lb = np.full(n, -1.0)
    ub = np.full(n, 0.8)
    return G, d, lb, ub


class TestFistaCore:
    def test_equivalence_with_trf(self):
        G, d, lb, ub = _random_box_problem()
        ref = lsq_linear(G, d, bounds=(lb, ub), method="trf",
                         lsq_solver="lsmr", tol=1e-10, max_iter=500)
        x_warm = np.clip(lsqr(G, d, iter_lim=500)[0], lb, ub)
        x, info = solve_inversion_pgd_fista(
            G, d, lb, ub, x0=x_warm, max_iter=2000, tol_pg=1e-8,
        )
        obj_ref = 0.5 * float(np.sum((G @ ref.x - d) ** 2))
        obj_fista = info["obj_final"]
        rel_diff = np.linalg.norm(x - ref.x) / max(np.linalg.norm(ref.x), 1e-12)
        assert rel_diff < 0.01, f"rel_diff={rel_diff:.4f} >= 1% vs TRF"
        assert obj_fista <= obj_ref * 1.001, (
            f"objetivo FISTA {obj_fista:.6e} > TRF {obj_ref:.6e} (+0.1%)"
        )

    def test_bounds_always_respected(self):
        G, d, lb, ub = _random_box_problem()
        x, _ = solve_inversion_pgd_fista(G, d, lb, ub, max_iter=300)
        assert np.all(x >= lb - 1e-12), "viola bound inferior"
        assert np.all(x <= ub + 1e-12), "viola bound superior"

    def test_objective_never_worse_than_clip_warmstart(self):
        G, d, lb, ub = _random_box_problem()
        x_clip = np.clip(lsqr(G, d, iter_lim=500)[0], lb, ub)
        obj_clip = 0.5 * float(np.sum((G @ x_clip - d) ** 2))
        _, info = solve_inversion_pgd_fista(G, d, lb, ub, x0=x_clip, max_iter=300)
        assert info["obj_warmstart"] == pytest.approx(obj_clip, rel=1e-9)
        assert info["obj_final"] <= obj_clip * (1 + 1e-12), (
            "FISTA empeoró el objetivo respecto al clip (garantía estructural rota)"
        )

    def test_improves_clip_when_bounds_bind(self):
        # Con la solución libre fuera del box, el clip es subóptimo:
        # FISTA debe mejorar el objetivo de forma material.
        G, d, lb, ub = _random_box_problem()
        x_clip = np.clip(lsqr(G, d, iter_lim=500)[0], lb, ub)
        obj_clip = 0.5 * float(np.sum((G @ x_clip - d) ** 2))
        _, info = solve_inversion_pgd_fista(G, d, lb, ub, x0=x_clip, max_iter=2000)
        assert info["obj_final"] < obj_clip * 0.99, (
            f"FISTA no mejoró materialmente: {info['obj_final']:.6e} vs clip {obj_clip:.6e}"
        )


# ══════════════════════════════════════════════════════════════════════════════
# Criterio 3 — caso crítico de producto: esfera compacta + no-negatividad
# ══════════════════════════════════════════════════════════════════════════════

@pytest.mark.integration
def test_sphere_nonnegativity_misfit_under_5pct():
    """Con density_min=2.6 (contraste >= 0) el clip dejaba misfit ~35%.

    Con FISTA proyectado el bound se satisface DENTRO de la optimización y
    el misfit debe bajar a < 5% (n_active ~13K → ruta LSQR+FISTA, no TRF).
    """
    import asyncio
    from test_field_data_complete_flow import build_field_csv
    from services.gravity_import_service import run_field_data_inversion_with_corrections
    from core.config import PROJECTS_DIR, USE_PROJECTED_SOLVER

    assert USE_PROJECTED_SOLVER, "Flag USE_PROJECTED_SOLVER debe estar ON por default"

    csv_text, _, _ = build_field_csv()
    tmp_csv = Path(__file__).parent.parent / "tmp" / f"pgd_sphere_{uuid.uuid4().hex[:6]}.csv"
    tmp_csv.parent.mkdir(exist_ok=True)
    tmp_csv.write_text(csv_text, encoding="utf-8")
    pid = f"test_pgd_{uuid.uuid4().hex[:6]}"
    try:
        r = asyncio.run(run_field_data_inversion_with_corrections(
            csv_path=tmp_csv, project_id=pid, run_id=uuid.uuid4().hex[:10],
            gravimeter_type="scintrex_cg6", apply_terrain=False,
            inversion_overrides=dict(
                nx=20, ny=10, nz=20, block_size=100, depth=1000,
                cutoff_radius=4000, lambda_mag=0.1,
                density_min=2.6,           # no-negatividad ESTRICTA (caso crítico)
                density_max=5.5,
            ),
        ))
        misfit = float(r["inversion_results"]["misfit_error_percent"])
        assert misfit < 5.0, (
            f"misfit={misfit:.1f}% con density_min=2.6 — el FISTA proyectado "
            "debería resolver el bound sin la degradación ~35% del clip."
        )
    finally:
        try:
            tmp_csv.unlink()
        except OSError:
            pass
        shutil.rmtree(Path(PROJECTS_DIR) / pid, ignore_errors=True)


@pytest.mark.slow
@pytest.mark.skipif(
    os.getenv("TQ_RUN_LARGE_BENCH") != "1",
    reason="Benchmark grande: exportar TQ_RUN_LARGE_BENCH=1",
)
def test_runtime_bounded_at_scale():
    """n=100K sintético: FISTA ≤ 5× el tiempo del LSQR puro."""
    import time
    n_rows, n = 40_000, 100_000
    G = sp.random(n_rows, n, density=0.0008, random_state=3, format="csr")
    G = sp.vstack([G, sp.eye(n) * 0.3]).tocsr()
    d = np.concatenate([RNG.standard_normal(n_rows), np.zeros(n)])
    lb, ub = np.full(n, -0.5), np.full(n, 0.5)

    t0 = time.perf_counter()
    x_raw = lsqr(G, d, iter_lim=500)[0]
    t_lsqr = time.perf_counter() - t0

    t0 = time.perf_counter()
    solve_inversion_pgd_fista(G, d, lb, ub, x0=np.clip(x_raw, lb, ub), max_iter=500)
    t_fista = time.perf_counter() - t0

    assert t_fista <= 5.0 * max(t_lsqr, 0.5), (
        f"FISTA {t_fista:.1f}s > 5x LSQR {t_lsqr:.1f}s"
    )
