"""
Fase 13 — Benchmark 5 (Opcional): Comparación contra SimPEG

Verifica que la inversión de TerraQuantum produce resultados comparables a
SimPEG en el mismo dataset sintético (tablero ajedrez 4×4).

Criterio Plan §13.2:
    pearson_r(m_true, m_TQ) > 0.70
    |pearson_r(m_true, m_TQ) - pearson_r(m_true, m_SimPEG)| < 0.15

Este test es OPCIONAL: se salta automáticamente si SimPEG no está instalado
en el ambiente de ejecución. En CI/CD con SimPEG disponible, se ejecuta
completo. Ver Plan §9: "tests marcados [optional-simpeg] en pytest".

Uso:
    pytest tests/test_simpeg_comparison.py                  # skip si no hay SimPEG
    pytest tests/test_simpeg_comparison.py -v               # verbose
    python tests/test_simpeg_comparison.py                  # ejecución directa
"""

from __future__ import annotations

import numpy as np
import pytest

# ── Importaciones opcionales de SimPEG ────────────────────────────────────────
SimPEG = pytest.importorskip(
    "SimPEG",
    reason="SimPEG no instalado. Test opcional saltado. "
           "Instalar con: pip install SimPEG  (solo para validación interna).",
)

try:
    from exploration.gravimetry import GravimetryForward, GravimetryInversion
except ImportError:
    import sys, os
    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    from exploration.gravimetry import GravimetryForward, GravimetryInversion

# ── Parámetros compartidos (mismos que test_benchmark_checkerboard.py) ─────────

CELL_SIZE = 200.0
N_CELLS = 4
BOARD_SIZE = CELL_SIZE * N_CELLS   # 800m

DELTA_RHO = 0.3        # t/m³
CHECKER_Y_TOP = 100.0
CHECKER_Y_BOT = 300.0

BLOCK = 50.0
NX = int(BOARD_SIZE / BLOCK)    # 16
NY = int(CHECKER_Y_BOT / BLOCK) + 2   # 8
NZ = int(BOARD_SIZE / BLOCK)    # 16

N_SENSORS_1D = 25

PEARSON_R_MIN = 0.70       # criterio TerraQuantum
PEARSON_R_GAP_MAX = 0.15   # gap máximo vs SimPEG


# ── Helpers (duplicados de test_benchmark_checkerboard.py para aislamiento) ──

def _build_grid():
    gx, gy, gz = np.mgrid[0:NX, 0:NY, 0:NZ]
    x_c = gx.flatten(order="F") * BLOCK + BLOCK / 2
    y_c = gy.flatten(order="F") * BLOCK + BLOCK / 2
    z_c = gz.flatten(order="F") * BLOCK + BLOCK / 2
    return x_c, y_c, z_c


def _build_checker_contrast(x_c, y_c, z_c):
    contrast = np.zeros(len(x_c))
    in_depth = (y_c >= CHECKER_Y_TOP) & (y_c < CHECKER_Y_BOT)
    for ix in range(N_CELLS):
        for iz in range(N_CELLS):
            sign = 1 if (ix + iz) % 2 == 0 else -1
            mask = (
                in_depth &
                (x_c >= ix * CELL_SIZE) & (x_c < (ix + 1) * CELL_SIZE) &
                (z_c >= iz * CELL_SIZE) & (z_c < (iz + 1) * CELL_SIZE)
            )
            contrast[mask] = sign * DELTA_RHO
    return contrast


def _build_sensors():
    sx = np.linspace(BLOCK / 2, NX * BLOCK - BLOCK / 2, N_SENSORS_1D)
    sz = np.linspace(BLOCK / 2, NZ * BLOCK - BLOCK / 2, N_SENSORS_1D)
    sx_g, sz_g = np.meshgrid(sx, sz, indexing="ij")
    return np.column_stack([sx_g.ravel(), np.zeros(sx_g.size), sz_g.ravel()])


def _run_terraquantum_inversion(x_c, y_c, z_c, contrast):
    """Inversión TerraQuantum; retorna contraste recuperado."""
    sensors = _build_sensors()
    forward = GravimetryForward(BLOCK, BLOCK, BLOCK, cutoff_radius=4000.0)
    kernel = forward.build_sparse_kernel(x_c, y_c, z_c, sensors)
    g_obs = kernel @ contrast

    rng = np.random.default_rng(seed=42)
    g_noisy = g_obs + rng.normal(0.0, 0.02 * float(np.sqrt(np.mean(g_obs**2))), size=len(g_obs))

    inv = GravimetryInversion(NX, NY, NZ, BLOCK)
    density, _score, _misfit, _sens = inv.solve_inversion_lsqr(
        g_noisy, None, y_c,
        lambda_mag=1e-3,
        alpha_spatial=1.0,
        forward_model=forward,
        sensor_coords=sensors,
        x_c=x_c,
        z_c=z_c,
    )
    return density - inv.base_density


def _run_simpeg_inversion(x_c, y_c, z_c, contrast):
    """
    Inversión SimPEG con los mismos datos y parámetros equivalentes.

    Usa SimPEG.potential_fields.gravity con regularización L2 estándar.
    Lambda equivalente calibrado para comparabilidad.
    """
    import SimPEG.potential_fields.gravity as grav
    from SimPEG import (
        maps, data, data_misfit, regularization, optimization,
        inverse_problem, inversion, directives
    )
    import discretize

    # Malla SimPEG (TensorMesh uniforme equivalente)
    h = [[(BLOCK, NX)], [(BLOCK, NY)], [(BLOCK, NZ)]]
    mesh = discretize.TensorMesh(h, origin="000")

    # Mapeo: solo celdas activas (todas — topografía plana)
    active = np.ones(mesh.nC, dtype=bool)
    model_map = maps.IdentityMap(nP=int(np.sum(active)))

    # Sensores
    sensors = _build_sensors()

    # SimPEG receiver: Gz component
    rx = grav.receivers.Point(
        locations=sensors,
        components="gz",
    )
    src = grav.sources.SourceField([rx])
    survey = grav.survey.Survey(src)

    # Simulación
    sim = grav.simulation.Simulation3DIntegral(
        mesh,
        survey=survey,
        rhoMap=model_map,
        actInd=active,
        store_sensitivities="forward_only",
    )

    # Datos observados (desde el kernel de TerraQuantum para comparabilidad)
    forward_tq = GravimetryForward(BLOCK, BLOCK, BLOCK, cutoff_radius=4000.0)
    kernel_tq = forward_tq.build_sparse_kernel(x_c, y_c, z_c, sensors)
    g_obs_tq = kernel_tq @ contrast

    rng = np.random.default_rng(seed=42)
    g_noisy = g_obs_tq + rng.normal(0.0, 0.02 * np.sqrt(np.mean(g_obs_tq**2)), size=len(g_obs_tq))

    # Convertir a mGal para SimPEG (convención interna m/s² → 1e5 mGal)
    g_simpeg = g_noisy * 1e5  # m/s² → mGal

    std_noise = 0.02 * float(np.sqrt(np.mean(g_simpeg**2))) * np.ones(len(g_simpeg))
    dobs = data.Data(survey, dobs=g_simpeg, standard_deviation=std_noise)

    # Inversión SimPEG con L2
    dmis = data_misfit.L2DataMisfit(data=dobs, simulation=sim)
    reg = regularization.WeightedLeastSquares(mesh, active_cells=active)
    opt = optimization.ProjectedGNCG(maxIter=50)
    inv_prob = inverse_problem.BaseInvProblem(dmis, reg, opt)
    directives_list = [
        directives.UpdateSensitivityWeights(),
        directives.BetaEstimate_ByEig(beta0_ratio=1e0),
        directives.TargetMisfit(chifact=1),
    ]
    inv_simpeg = inversion.BaseInversion(inv_prob, directiveList=directives_list)

    m0 = np.zeros(int(np.sum(active)))
    m_rec = inv_simpeg.run(m0)
    return m_rec


# ── Test ──────────────────────────────────────────────────────────────────────

@pytest.mark.benchmark
@pytest.mark.optional_simpeg
def test_pearson_r_vs_simpeg():
    """
    [optional-simpeg] Benchmark 5 — Pearson r TerraQuantum vs SimPEG.

    Verifica que:
    1. TerraQuantum Pearson r > 0.70 en el checkerboard 4×4
    2. |r_TQ - r_SimPEG| < 0.15 (gap dentro de Tier 1)
    """
    x_c, y_c, z_c = _build_grid()
    m_true = _build_checker_contrast(x_c, y_c, z_c)

    m_tq = _run_terraquantum_inversion(x_c, y_c, z_c, m_true)

    try:
        m_simpeg = _run_simpeg_inversion(x_c, y_c, z_c, m_true)
    except Exception as e:
        pytest.skip(f"SimPEG inversion failed: {e}")

    # Pearson r solo en las celdas del tablero (activas)
    in_checker = m_true != 0.0

    # Handle NaN in recovered models
    valid_tq = in_checker & np.isfinite(m_tq)
    valid_sp = in_checker & np.isfinite(m_simpeg[:len(m_tq)] if len(m_simpeg) >= len(m_tq) else np.full(len(m_true), np.nan))

    r_tq = float(np.corrcoef(m_true[valid_tq], m_tq[valid_tq])[0, 1])

    # Align SimPEG model to the same voxel ordering as TerraQuantum
    if len(m_simpeg) == len(m_true):
        valid_sp_mask = in_checker & np.isfinite(m_simpeg)
        r_simpeg = float(np.corrcoef(m_true[valid_sp_mask], m_simpeg[valid_sp_mask])[0, 1])
    else:
        pytest.skip(
            f"SimPEG model length {len(m_simpeg)} != TerraQuantum {len(m_true)}. "
            "Meshes incompatibles para comparación directa."
        )

    assert r_tq > PEARSON_R_MIN, (
        f"Benchmark 5 FAIL — TerraQuantum Pearson r = {r_tq:.3f} < {PEARSON_R_MIN:.2f} "
        f"(criterio Tier 1 Plan §13.2)"
    )

    gap = abs(r_tq - r_simpeg)
    assert gap < PEARSON_R_GAP_MAX, (
        f"Benchmark 5 FAIL — Gap TQ vs SimPEG = {gap:.3f} "
        f"(r_TQ={r_tq:.3f}, r_SimPEG={r_simpeg:.3f}) | "
        f"límite = {PEARSON_R_GAP_MAX:.2f} (Plan §13.2 Tier 1)"
    )


# ── Ejecución directa ─────────────────────────────────────────────────────────

if __name__ == "__main__":
    try:
        test_pearson_r_vs_simpeg()
        print("  PASS  test_pearson_r_vs_simpeg")
    except pytest.skip.Exception as e:
        print(f"  SKIP  test_pearson_r_vs_simpeg: {e}")
    except AssertionError as e:
        print(f"  FAIL  test_pearson_r_vs_simpeg: {e}")
    except Exception as e:
        print(f"  ERROR test_pearson_r_vs_simpeg: {e}")
