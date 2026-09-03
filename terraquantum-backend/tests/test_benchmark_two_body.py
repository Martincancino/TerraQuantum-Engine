"""
Fase 13 — Benchmark 4: Dos Cuerpos Interferentes (Separabilidad)

Verifica que el motor de inversión puede resolver dos anomalías de densidad
espacialmente separadas y recuperar sus posiciones con la precisión requerida.

Parámetros del Plan Industrial §13.2:
    Cuerpo A: ρ=0.5 t/m³ de contraste, centro en (500m, 300m profundidad)
    Cuerpo B: ρ=0.3 t/m³ de contraste, centro en (1500m, 500m profundidad)
    Criterio Tier 1: centroide de cada anomalía recuperado a ± 150m del verdadero

Metodología de evaluación:
    El modelo recuperado se divide en dos ventanas espaciales (x<1000m y x≥1000m).
    El centroide del top-30% de cada ventana se compara con la posición verdadera.

Implementación:
    Fixture de módulo (scope="module") para que la inversión se corra una sola vez
    y los tres sub-tests compartan el resultado — evita 3× el tiempo de cómputo.

Convención espacial del backend:
    x, z = horizontales;  y = profundidad positiva hacia abajo.
    Sensores en y=0 (superficie).
"""

from __future__ import annotations

import numpy as np
import pytest

try:
    from tests.seed_sweep import bench_seeds, median_of, spread_report
except ImportError:                                    # ejecucion directa del archivo
    from seed_sweep import bench_seeds, median_of, spread_report

try:
    from exploration.gravimetry import GravimetryForward, GravimetryInversion
except ImportError:
    import sys, os
    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    from exploration.gravimetry import GravimetryForward, GravimetryInversion

# ── Parámetros del benchmark ──────────────────────────────────────────────────

# Posiciones verdaderas del Plan §13.2
BODY_A_X = 500.0
BODY_A_Y = 300.0
BODY_A_RHO = 0.5    # t/m³
BODY_A_R = 100.0    # m radio

BODY_B_X = 1500.0
BODY_B_Y = 500.0
BODY_B_RHO = 0.3    # t/m³
BODY_B_R = 100.0    # m radio

# Grilla de inversión: BLOCK=75m para mantener n_active < 1000
# (los cuerpos tienen R=100m = 1.3 celdas → bien representados con ~5-10 vóxeles cada uno)
BLOCK = 75.0
NX = 23     # 1725m en x (cubre hasta body B en x=1500m + margen)
NY = 9      # 675m en profundidad (cubre body B en y=500m)
NZ = 2      # 150m en z (thin domain, bodies centrados)

Z_CENTER = NZ * BLOCK / 2   # 75m

CENTROID_TOL_M = 150.0       # m — tolerancia plan §13.2
LAMBDA = 5e-4


# ── Helpers ───────────────────────────────────────────────────────────────────

def _build_grid():
    gx, gy, gz = np.mgrid[0:NX, 0:NY, 0:NZ]
    x_c = gx.flatten(order="F") * BLOCK + BLOCK / 2
    y_c = gy.flatten(order="F") * BLOCK + BLOCK / 2
    z_c = gz.flatten(order="F") * BLOCK + BLOCK / 2
    return x_c, y_c, z_c


def _build_two_body_contrast(x_c, y_c, z_c):
    r_a = np.sqrt((x_c - BODY_A_X)**2 + (y_c - BODY_A_Y)**2 + (z_c - Z_CENTER)**2)
    r_b = np.sqrt((x_c - BODY_B_X)**2 + (y_c - BODY_B_Y)**2 + (z_c - Z_CENTER)**2)
    contrast = np.zeros(len(x_c), dtype=np.float64)
    contrast[r_a <= BODY_A_R] = BODY_A_RHO
    contrast[r_b <= BODY_B_R] = BODY_B_RHO
    return contrast


def _build_sensors():
    """20×2 = 40 sensores en y=0 cubriendo el dominio XZ."""
    sx = np.linspace(BLOCK / 2, NX * BLOCK - BLOCK / 2, 20)
    sz = np.linspace(BLOCK / 2, NZ * BLOCK - BLOCK / 2, 2)
    sx_g, sz_g = np.meshgrid(sx, sz, indexing="ij")
    return np.column_stack([sx_g.ravel(), np.zeros(sx_g.size), sz_g.ravel()])


# ── Fixture compartida (inversión corre una sola vez) ─────────────────────────

@pytest.fixture(scope="module")
def two_body_inversion_result():
    """
    Corre la inversión una única vez para los tres sub-tests del Benchmark 4.
    scope="module" garantiza re-uso entre test_two_body_centroid_a/b/separation.

    TRF bounded se mantiene (NO monkeypatch): para n_active=414 TRF toma ~3.4s
    y da chi2=0 (ajuste perfecto), lo que es necesario para el centroide correcto.
    Con LSQR (chi2=18.5), el centroide del cuerpo A se desplaza ~190m.
    """
    x_c, y_c, z_c = _build_grid()
    contrast_true = _build_two_body_contrast(x_c, y_c, z_c)

    sensors = _build_sensors()
    forward = GravimetryForward(BLOCK, BLOCK, BLOCK, cutoff_radius=3500.0)
    kernel = forward.build_sparse_kernel(x_c, y_c, z_c, sensors)
    g_obs = kernel @ contrast_true

    assert np.max(np.abs(g_obs)) > 0, "g_obs es cero — revisar geometría"
    assert np.isfinite(g_obs).all()

    # FASE 26 (direccion 5): una realizacion de ruido POR SEMILLA. El kernel —lo caro—
    # se construyo una sola vez arriba; cada semilla solo anade un solve.
    seeds = bench_seeds()
    sigma = 0.02 * float(np.sqrt(np.mean(g_obs**2)))
    recs = []
    for sd in seeds:
        rng = np.random.default_rng(seed=int(sd))
        g_noisy = g_obs + rng.normal(0.0, sigma, size=len(g_obs))
        inv = GravimetryInversion(NX, NY, NZ, BLOCK)
        density, _score, _misfit, _sens = inv.solve_inversion_lsqr(
            g_noisy, None, y_c,
            lambda_mag=LAMBDA,
            alpha_spatial=1.0,
            forward_model=forward,
            sensor_coords=sensors,
            x_c=x_c,
            z_c=z_c,
        )
        recs.append(density - inv.base_density)
    return x_c, y_c, z_c, contrast_true, recs, seeds


# ── Helpers post-inversión ────────────────────────────────────────────────────

def _dists(x_c, y_c, z_c, recs, x_lo, x_hi, true_x, true_y):
    """Distancia del centroide recuperado al verdadero, UNA POR SEMILLA."""
    out = []
    for rec in recs:
        cx, cy = _centroid_in_window(x_c, y_c, z_c, rec, x_lo, x_hi)
        out.append(float("nan") if cx is None
                   else float(np.sqrt((cx - true_x) ** 2 + (cy - true_y) ** 2)))
    return out



def _centroid_in_window(x_c, y_c, z_c, contrast_rec, x_lo, x_hi):
    """Centroide (x, y) del top-30% del contraste en la ventana x=[x_lo, x_hi]."""
    window = (x_c >= x_lo) & (x_c < x_hi) & np.isfinite(contrast_rec) & (contrast_rec > 0)
    if not window.any():
        return None, None
    c_win = contrast_rec[window]
    threshold = np.percentile(c_win, 70)
    strong = window & (contrast_rec >= threshold)
    if not strong.any():
        strong = window
    cx = float(np.average(x_c[strong], weights=contrast_rec[strong]))
    cy = float(np.average(y_c[strong], weights=contrast_rec[strong]))
    return cx, cy


# ── Tests ──────────────────────────────────────────────────────────────────────

@pytest.mark.benchmark
def test_two_body_centroid_a(two_body_inversion_result):
    """
    Benchmark 4a — Centroide del cuerpo A (ρ=0.5, x=500m, y=300m) ± 150m.
    """
    x_c, y_c, z_c, contrast_true, recs, seeds = two_body_inversion_result

    n_a = int(np.sum((np.sqrt((x_c - BODY_A_X)**2 + (y_c - BODY_A_Y)**2 + (z_c - Z_CENTER)**2)) <= BODY_A_R))
    assert n_a >= 1, f"Cuerpo A tiene solo {n_a} vóxeles — dominio insuficiente"

    half_x = NX * BLOCK / 2
    dists = _dists(x_c, y_c, z_c, recs, 0.0, half_x, BODY_A_X, BODY_A_Y)
    assert any(d == d for d in dists), (
        "No se recuperó contraste positivo en el dominio del cuerpo A (x < "
        f"{half_x:.0f}m) en NINGUNA semilla. Revisar lambda o cutoff_radius."
    )

    mediana = median_of(dists)
    assert mediana <= CENTROID_TOL_M, (
        f"Benchmark 4a FAIL — Centroide A, distancia al verdadero "
        f"({BODY_A_X:.0f}m, {BODY_A_Y:.0f}m), MEDIANA sobre {len(seeds)} semillas: "
        f"{mediana:.1f}m | tol=±{CENTROID_TOL_M:.0f}m (Plan §13.2)\n"
        f"    {spread_report(seeds, dists, unit='m')}"
    )


@pytest.mark.benchmark
def test_two_body_centroid_b(two_body_inversion_result):
    """
    Benchmark 4b — Centroide del cuerpo B (ρ=0.3, x=1500m, y=500m) ± 150m.
    """
    x_c, y_c, z_c, contrast_true, recs, seeds = two_body_inversion_result

    n_b = int(np.sum((np.sqrt((x_c - BODY_B_X)**2 + (y_c - BODY_B_Y)**2 + (z_c - Z_CENTER)**2)) <= BODY_B_R))
    assert n_b >= 1, f"Cuerpo B tiene solo {n_b} vóxeles — dominio insuficiente"

    half_x = NX * BLOCK / 2
    dists = _dists(x_c, y_c, z_c, recs, half_x, NX * BLOCK, BODY_B_X, BODY_B_Y)
    assert any(d == d for d in dists), (
        "No se recuperó contraste positivo en el dominio del cuerpo B (x ≥ "
        f"{half_x:.0f}m) en NINGUNA semilla. Revisar lambda o cutoff_radius."
    )

    mediana = median_of(dists)
    assert mediana <= CENTROID_TOL_M, (
        f"Benchmark 4b FAIL — Centroide B, distancia al verdadero "
        f"({BODY_B_X:.0f}m, {BODY_B_Y:.0f}m), MEDIANA sobre {len(seeds)} semillas: "
        f"{mediana:.1f}m | tol=±{CENTROID_TOL_M:.0f}m (Plan §13.2)\n"
        f"    {spread_report(seeds, dists, unit='m')}"
    )


@pytest.mark.benchmark
def test_two_body_separation(two_body_inversion_result):
    """
    Benchmark 4c — Los dos cuerpos son distinguibles: hay contraste positivo
    en ambos dominios espaciales (x<1000m y x≥1000m).
    """
    x_c, y_c, z_c, contrast_true, recs, seeds = two_body_inversion_result

    half_x = NX * BLOCK / 2
    izq, der = [], []
    for rec in recs:
        threshold = 0.20 * float(np.nanmax(rec))
        ok = np.isfinite(rec) & (rec > threshold)
        izq.append(float(np.sum((x_c < half_x) & ok)))
        der.append(float(np.sum((x_c >= half_x) & ok)))

    # La MEDIANA de las semillas tiene que separar los dos cuerpos, no una tirada.
    assert median_of(izq) >= 1, (
        f"No se recuperó anomalía en dominio cuerpo A (x < {half_x:.0f}m)\n"
        f"    {spread_report(seeds, izq, unit=' vox')}")
    assert median_of(der) >= 1, (
        f"No se recuperó anomalía en dominio cuerpo B (x ≥ {half_x:.0f}m)\n"
        f"    {spread_report(seeds, der, unit=' vox')}")


# ── Ejecución directa ─────────────────────────────────────────────────────────

if __name__ == "__main__":
    import traceback, time

    print("[two_body] Corriendo inversión una vez ...")
    t0 = time.perf_counter()
    x_c, y_c, z_c = _build_grid()
    contrast = _build_two_body_contrast(x_c, y_c, z_c)
    sensors = _build_sensors()
    forward = GravimetryForward(BLOCK, BLOCK, BLOCK, cutoff_radius=3500.0)
    kernel = forward.build_sparse_kernel(x_c, y_c, z_c, sensors)
    g_obs = kernel @ contrast
    seeds = bench_seeds()
    sigma = 0.02 * float(np.sqrt(np.mean(g_obs**2)))
    recs = []
    for sd in seeds:
        rng = np.random.default_rng(int(sd))
        g_noisy = g_obs + rng.normal(0.0, sigma, size=len(g_obs))
        inv = GravimetryInversion(NX, NY, NZ, BLOCK)
        density, _s, _m, _e = inv.solve_inversion_lsqr(
            g_noisy, None, y_c, lambda_mag=LAMBDA, alpha_spatial=1.0,
            forward_model=forward, sensor_coords=sensors, x_c=x_c, z_c=z_c,
        )
        recs.append(density - inv.base_density)
    print(f"  {len(seeds)} inversiones: {time.perf_counter()-t0:.1f}s")

    result = (x_c, y_c, z_c, contrast, recs, seeds)

    passed = failed = 0
    for fn in [test_two_body_separation, test_two_body_centroid_a, test_two_body_centroid_b]:
        try:
            fn(result)
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
    print(f"test_benchmark_two_body — {passed} PASS / {failed} FAIL")
    if failed:
        import sys; sys.exit(1)
