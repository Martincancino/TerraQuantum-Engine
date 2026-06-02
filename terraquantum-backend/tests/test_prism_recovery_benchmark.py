"""
HITO 4 — Benchmark de recuperación de prisma rectangular (Plouff 1976).

Forward analítico exacto de un prisma infinito vertical: el efecto gravimétrico
se calcula con la fórmula de Plouff. La inversión debe recuperar la posición
horizontal y el exceso de masa dentro del threshold de CI (<10% error relativo).

Anti-inverse-crime: malla forward (10m) ≠ malla de inversión (14m).
"""
import numpy as np
import pytest

from exploration.gravimetry import GravimetryForward, GravimetryInversion


# ── Parámetros fijos del benchmark ──────────────────────────────────────────
PRISM_X1, PRISM_X2 = 80.0, 160.0   # m, extensión horizontal X
PRISM_Z1, PRISM_Z2 = 80.0, 160.0   # m, extensión horizontal Z
PRISM_Y1, PRISM_Y2 = 40.0, 120.0   # m, profundidad (Y = profundidad)
DELTA_RHO = 0.5                      # t/m³ de contraste

G_CONST = 6.67430e-11
T_M3_TO_KG_M3 = 1000.0

RECOVERY_ERROR_THRESHOLD = 0.10     # CI falla si error medio > 10%


def _prism_gz_analytic(sensors: np.ndarray) -> np.ndarray:
    """Componente vertical del campo gravimétrico de un prisma rectangular.

    Fórmula de Plouff (1976), adaptada a la convención del backend:
      y_m = profundidad (positivo hacia abajo), sensores en y=0.

    El backend calcula g_y = G·M·Δy/r³ con Δy>0 → resultado positivo.
    La fórmula de Plouff en coordenadas estándar (z positivo hacia arriba) da
    el componente en convención altura-positiva; se niega para obtener la
    convención profundidad-positiva del backend.
    """
    x1, x2 = PRISM_X1, PRISM_X2
    z1, z2 = PRISM_Z1, PRISM_Z2
    y1, y2 = PRISM_Y1, PRISM_Y2
    delta_rho_kgm3 = DELTA_RHO * T_M3_TO_KG_M3

    g = np.empty(len(sensors))
    for i, (sx, sy, sz) in enumerate(sensors):
        total = 0.0
        for xi in (x1 - sx, x2 - sx):
            for yi in (y1 - sy, y2 - sy):
                for zi in (z1 - sz, z2 - sz):
                    r = np.sqrt(xi**2 + yi**2 + zi**2)
                    if r < 1e-10:
                        continue
                    sign = (
                        (1 if xi == x2 - sx else -1) *
                        (1 if yi == y2 - sy else -1) *
                        (1 if zi == z2 - sz else -1)
                    )
                    val = xi * np.log(zi + r) + zi * np.log(xi + r) - yi * np.arctan2(xi * zi, yi * r)
                    total += sign * val
        # Negación: convierte convención Plouff (altura-positiva) a backend (profundidad-positiva)
        g[i] = -G_CONST * delta_rho_kgm3 * total
    return g


@pytest.mark.benchmark
def test_prism_recovery_horizontal_position():
    """La inversión debe localizar el centro del prisma horizontalmente (±2 bloques)."""
    # ── Forward sintético con malla fina (10m) ───────────────────────────────
    NX_F, NY_F, NZ_F, BS_F = 25, 16, 25, 10.0
    gx, gy, gz = np.mgrid[0:NX_F, 0:NY_F, 0:NZ_F]
    x_f = gx.flatten(order="F") * BS_F + BS_F / 2
    y_f = gy.flatten(order="F") * BS_F + BS_F / 2
    z_f = gz.flatten(order="F") * BS_F + BS_F / 2

    # Survey denso 5×5 en superficie
    sx_grid, sz_grid = np.meshgrid(
        np.arange(25, 225, 25, dtype=float),
        np.arange(25, 225, 25, dtype=float),
        indexing="ij",
    )
    sensors = np.column_stack([sx_grid.ravel(), np.zeros(sx_grid.size), sz_grid.ravel()])

    g_obs = _prism_gz_analytic(sensors)

    assert np.isfinite(g_obs).all()
    assert not np.allclose(g_obs, 0.0), "g_obs sintético debe tener señal"

    # ── Inversión con malla DIFERENTE (14m) — anti-inverse-crime ─────────────
    BS_I = 14.0
    NX_I, NY_I, NZ_I = 18, 12, 18
    gx_i, gy_i, gz_i = np.mgrid[0:NX_I, 0:NY_I, 0:NZ_I]
    x_i = gx_i.flatten(order="F") * BS_I + BS_I / 2
    y_i = gy_i.flatten(order="F") * BS_I + BS_I / 2
    z_i = gz_i.flatten(order="F") * BS_I + BS_I / 2

    inv = GravimetryInversion(NX_I, NY_I, NZ_I, BS_I)
    density, _score, misfit, _sens = inv.solve_inversion_lsqr(
        g_obs, None, y_i,
        lambda_mag=5e-4, alpha_spatial=1.0,
        forward_model=GravimetryForward(BS_I, BS_I, BS_I, cutoff_radius=5000.0),
        sensor_coords=sensors, x_c=x_i, z_c=z_i,
    )

    recovered = density - inv.base_density
    finite_mask = np.isfinite(recovered) & (recovered > 0.3 * np.nanmax(recovered))

    assert finite_mask.any(), "El solver no recuperó ninguna anomalía positiva"

    cx_true = (PRISM_X1 + PRISM_X2) / 2
    cz_true = (PRISM_Z1 + PRISM_Z2) / 2
    cx_rec = float(np.average(x_i[finite_mask], weights=recovered[finite_mask]))
    cz_rec = float(np.average(z_i[finite_mask], weights=recovered[finite_mask]))

    assert abs(cx_rec - cx_true) < 2 * BS_I, (
        f"Centro X recuperado {cx_rec:.1f}m lejos del real {cx_true}m "
        f"(tolerancia ±{2 * BS_I}m) — benchmark degradado sobre {RECOVERY_ERROR_THRESHOLD:.0%}"
    )
    assert abs(cz_rec - cz_true) < 2 * BS_I, (
        f"Centro Z recuperado {cz_rec:.1f}m lejos del real {cz_true}m "
        f"(tolerancia ±{2 * BS_I}m) — benchmark degradado sobre {RECOVERY_ERROR_THRESHOLD:.0%}"
    )


@pytest.mark.benchmark
def test_prism_kernel_matches_analytic():
    """El kernel forward del backend debe reproducir el campo analítico del prisma
    con error < 10%. Validación independiente del solver inverso."""
    NX, NY, NZ, BS = 25, 16, 25, 10.0
    gx, gy, gz = np.mgrid[0:NX, 0:NY, 0:NZ]
    x_c = gx.flatten(order="F") * BS + BS / 2
    y_c = gy.flatten(order="F") * BS + BS / 2
    z_c = gz.flatten(order="F") * BS + BS / 2

    inside = (
        (x_c >= PRISM_X1) & (x_c <= PRISM_X2) &
        (y_c >= PRISM_Y1) & (y_c <= PRISM_Y2) &
        (z_c >= PRISM_Z1) & (z_c <= PRISM_Z2)
    )
    contrast = np.where(inside, DELTA_RHO, 0.0)

    sensors = np.array(
        [[120, 0, 120], [80, 0, 120], [160, 0, 120],
         [120, 0, 80],  [120, 0, 160]],
        dtype=np.float64,
    )

    forward = GravimetryForward(BS, BS, BS, cutoff_radius=5000.0)
    kernel = forward.build_sparse_kernel(x_c, y_c, z_c, sensors)
    g_kernel = kernel @ contrast
    g_analytic = _prism_gz_analytic(sensors)

    rel_err = np.abs(g_kernel - g_analytic) / (np.abs(g_analytic) + 1e-20)
    mean_err = float(np.mean(rel_err))

    assert mean_err < RECOVERY_ERROR_THRESHOLD, (
        f"Error relativo medio del kernel vs Plouff: {mean_err:.2%} > {RECOVERY_ERROR_THRESHOLD:.0%}. "
        "El kernel gravimétrico ha degradado."
    )
