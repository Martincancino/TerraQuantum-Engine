"""
Fase 13 - Benchmark 3: Tablero Ajedrez 4x4 (Resolucion Espacial)

Verifica la capacidad de resolucion espacial del motor de inversion mediante
un tablero ajedrez de celdas con contrastes alternados de densidad.

Parametros del Plan Industrial 13.2:
    Tablero: 4x4 celdas de 200x200m, alternando rho=+0.3 y -0.3 t/m3
    Profundidad del tablero: 100-300m (capa de 200m de espesor)
    Red de sensores: 25x25 sobre el tablero (800x800m de cobertura)
    Criterio Tier 1: > 80% de celdas con signo correcto en el modelo recuperado

Metodologia de evaluacion:
    Para cada una de las 16 celdas del tablero, se computa el contraste medio
    en los voxeles de inversion que la contienen. Si el signo del contraste
    medio coincide con el signo verdadero, la celda "pasa". La tasa de exito
    de signo debe superar el 80% (>=13/16 celdas).

Convencion espacial del backend:
    x, z = horizontales;  y = profundidad positiva hacia abajo.
    Sensores en y=0 (superficie).
"""

from __future__ import annotations

import numpy as np
import pytest

try:
    from exploration.gravimetry import GravimetryForward, GravimetryInversion
except ImportError:
    import sys, os
    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    from exploration.gravimetry import GravimetryForward, GravimetryInversion

# -- Parametros del benchmark --------------------------------------------------

CELL_SIZE = 200.0        # m
N_CELLS = 4              # 4x4 = 16 celdas en total
BOARD_SIZE = CELL_SIZE * N_CELLS    # 800m

DELTA_RHO = 0.3          # t/m3

CHECKER_Y_TOP = 100.0
CHECKER_Y_BOT = 300.0

BLOCK = 50.0
NX = int(BOARD_SIZE / BLOCK)    # 16
NY = int(CHECKER_Y_BOT / BLOCK) + 2    # 8
NZ = int(BOARD_SIZE / BLOCK)    # 16

N_SENSORS_1D = 25
LAMBDA = 1e-3

SIGN_CORRECT_MIN = 0.80


# -- Helpers -------------------------------------------------------------------

def _build_grid():
    gx, gy, gz = np.mgrid[0:NX, 0:NY, 0:NZ]
    x_c = gx.flatten(order="F") * BLOCK + BLOCK / 2
    y_c = gy.flatten(order="F") * BLOCK + BLOCK / 2
    z_c = gz.flatten(order="F") * BLOCK + BLOCK / 2
    return x_c, y_c, z_c


def _checker_sign(ix: int, iz: int) -> int:
    return 1 if (ix + iz) % 2 == 0 else -1


def _build_checker_contrast(x_c, y_c, z_c):
    contrast = np.zeros(len(x_c), dtype=np.float64)
    in_depth = (y_c >= CHECKER_Y_TOP) & (y_c < CHECKER_Y_BOT)
    for ix in range(N_CELLS):
        in_x = (x_c >= ix * CELL_SIZE) & (x_c < (ix + 1) * CELL_SIZE)
        for iz in range(N_CELLS):
            in_z = (z_c >= iz * CELL_SIZE) & (z_c < (iz + 1) * CELL_SIZE)
            cell_mask = in_depth & in_x & in_z
            if cell_mask.any():
                contrast[cell_mask] = _checker_sign(ix, iz) * DELTA_RHO
    return contrast


def _build_sensors():
    sx = np.linspace(BLOCK / 2, NX * BLOCK - BLOCK / 2, N_SENSORS_1D)
    sz = np.linspace(BLOCK / 2, NZ * BLOCK - BLOCK / 2, N_SENSORS_1D)
    sx_g, sz_g = np.meshgrid(sx, sz, indexing="ij")
    return np.column_stack([sx_g.ravel(), np.zeros(sx_g.size), sz_g.ravel()])


def _run_checkerboard_inversion(x_c, y_c, z_c, contrast):
    """Computa datos y recupera modelo; retorna contraste recuperado.
    USE_BOUNDED_SOLVER debe estar en False antes de llamar (configurado por fixture).
    """
    sensors = _build_sensors()
    forward = GravimetryForward(BLOCK, BLOCK, BLOCK, cutoff_radius=4000.0)
    kernel = forward.build_sparse_kernel(x_c, y_c, z_c, sensors)
    g_obs = kernel @ contrast

    assert np.max(np.abs(g_obs)) > 0, "g_obs checkerboard es cero"
    assert np.isfinite(g_obs).all()

    rng = np.random.default_rng(seed=42)
    noise = rng.normal(0.0, 0.02 * float(np.sqrt(np.mean(g_obs**2))), size=len(g_obs))
    g_noisy = g_obs + noise

    inv = GravimetryInversion(NX, NY, NZ, BLOCK)
    density, _score, _misfit, _sens = inv.solve_inversion_lsqr(
        g_noisy, None, y_c,
        lambda_mag=LAMBDA,
        alpha_spatial=1.0,
        forward_model=forward,
        sensor_coords=sensors,
        x_c=x_c,
        z_c=z_c,
        density_min=1.8,   # permite contraste negativo (delta_rho=-0.3)
        density_max=4.0,
    )
    return density - inv.base_density


# -- Fixture compartida --------------------------------------------------------

@pytest.fixture(scope="module")
def checker_inversion_result():
    """
    Corre la inversion del tablero una unica vez.
    USE_BOUNDED_SOLVER forzado a False (LSQR+clip) para evitar TRF >500s
    en dominios < 8000 voxeles.
    """
    import core.config as _cfg
    _orig_bounded = _cfg.USE_BOUNDED_SOLVER
    _cfg.USE_BOUNDED_SOLVER = False

    try:
        x_c, y_c, z_c = _build_grid()
        contrast_true = _build_checker_contrast(x_c, y_c, z_c)
        n_checker = int(np.sum(contrast_true != 0))
        assert n_checker >= N_CELLS * N_CELLS, (
            f"Tablero tiene solo {n_checker} voxeles — revisar dominio"
        )
        contrast_rec = _run_checkerboard_inversion(x_c, y_c, z_c, contrast_true)
        return x_c, y_c, z_c, contrast_true, contrast_rec
    finally:
        _cfg.USE_BOUNDED_SOLVER = _orig_bounded


# -- Tests ---------------------------------------------------------------------

@pytest.mark.benchmark
def test_checkerboard_sign_recovery(checker_inversion_result):
    """
    Benchmark 3 — Resolucion espacial: > 80% celdas con signo correcto.
    """
    x_c, y_c, z_c, contrast_true, contrast_rec = checker_inversion_result

    correct = 0
    total = N_CELLS * N_CELLS
    cell_results = []

    in_depth = (y_c >= CHECKER_Y_TOP) & (y_c < CHECKER_Y_BOT) & np.isfinite(contrast_rec)

    for ix in range(N_CELLS):
        x_lo, x_hi = ix * CELL_SIZE, (ix + 1) * CELL_SIZE
        for iz in range(N_CELLS):
            z_lo, z_hi = iz * CELL_SIZE, (iz + 1) * CELL_SIZE
            cell_mask = in_depth & (x_c >= x_lo) & (x_c < x_hi) & (z_c >= z_lo) & (z_c < z_hi)

            if not cell_mask.any():
                total -= 1
                continue

            mean_contrast = float(np.mean(contrast_rec[cell_mask]))
            true_sign = _checker_sign(ix, iz)
            recovered_sign = 1 if mean_contrast >= 0 else -1

            if recovered_sign == true_sign:
                correct += 1

            cell_results.append({
                "cell": (ix, iz),
                "true_sign": true_sign,
                "mean_rec": round(mean_contrast, 4),
                "recovered_sign": recovered_sign,
                "pass": recovered_sign == true_sign,
            })

    assert total > 0, "No se encontraron celdas del tablero en el dominio"

    sign_pct = correct / total
    details = "\n  ".join(
        f"({r['cell'][0]},{r['cell'][1]}) true={r['true_sign']:+d} rec={r['mean_rec']:+.4f} "
        f"{'PASS' if r['pass'] else 'FAIL'}"
        for r in cell_results
    )

    assert sign_pct >= SIGN_CORRECT_MIN, (
        f"Benchmark 3 FAIL — Signo correcto: {correct}/{total} = {sign_pct:.0%} "
        f"(criterio Tier 1: >={SIGN_CORRECT_MIN:.0%})\n"
        f"  Detalle por celda:\n  {details}"
    )


@pytest.mark.benchmark
def test_checkerboard_forward_signal():
    """
    Verificacion auxiliar: la senal de datos del tablero supera 5x el ruido
    instrumental (0.5 uGal). No requiere inversion.
    """
    x_c, y_c, z_c = _build_grid()
    contrast_true = _build_checker_contrast(x_c, y_c, z_c)
    sensors = _build_sensors()

    forward = GravimetryForward(BLOCK, BLOCK, BLOCK, cutoff_radius=4000.0)
    kernel = forward.build_sparse_kernel(x_c, y_c, z_c, sensors)
    g_obs = kernel @ contrast_true

    data_rms = float(np.sqrt(np.mean(g_obs**2)))
    instrument_noise = 5e-9   # 0.5 uGal

    assert data_rms > 5 * instrument_noise, (
        f"Senal del tablero demasiado debil: RMS={data_rms:.2e} m/s2 | "
        f"5x ruido={5*instrument_noise:.2e} m/s2"
    )


# -- Ejecucion directa ---------------------------------------------------------

if __name__ == "__main__":
    import traceback, time, core.config as _cfg

    _cfg.USE_BOUNDED_SOLVER = False
    x_c, y_c, z_c = _build_grid()
    contrast = _build_checker_contrast(x_c, y_c, z_c)
    print(f"[checkerboard] {NX}x{NY}x{NZ} = {NX*NY*NZ} vox, {N_CELLS}x{N_CELLS} celdas")

    t0 = time.perf_counter()
    contrast_rec = _run_checkerboard_inversion(x_c, y_c, z_c, contrast)
    print(f"  Inversion: {time.perf_counter()-t0:.1f}s")

    result = (x_c, y_c, z_c, contrast, contrast_rec)

    passed = failed = 0
    for fn, arg in [
        (test_checkerboard_forward_signal, None),
        (test_checkerboard_sign_recovery, result),
    ]:
        try:
            fn(arg) if arg is not None else fn()
            print(f"  PASS  {fn.__name__}")
            passed += 1
        except AssertionError as e:
            print(f"  FAIL  {fn.__name__}: {e}")
            failed += 1
        except Exception:
            print(f"  ERROR {fn.__name__}")
            traceback.print_exc()
            failed += 1

    print(f"\n{'='*60}")
    print(f"test_benchmark_checkerboard — {passed} PASS / {failed} FAIL")
    if failed:
        import sys; sys.exit(1)
