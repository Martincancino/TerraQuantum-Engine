"""
Track 4 / T4.1 — Validación formal del kernel gravimétrico contra solución analítica.
HITO 4 — Protocolo anti-inverse-crime agregado (test_inversion_anti_inverse_crime).

La gravedad de una esfera uniforme en un punto EXTERNO es idéntica a la de una masa
puntual concentrada en su centro:

    g(r) = G · M / r²,     componente vertical  g_y = G · M · Δy / r³

con M = (4/3)·π·R³·Δρ·1000  (Δρ en t/m³ → kg/m³). Discretizamos una esfera en vóxeles,
sumamos el kernel del forward model y comparamos contra la fórmula de masa puntual
(usando la masa REALMENTE discretizada en el centroide). Para sensores a r ≫ R el
error multipolar es O((R/r)²); se exige un acuerdo estrecho.

Esta es la prueba "gold standard": valida que el kernel integra la masa correcta y
reproduce la caída 1/r² física, independiente del solver inverso.
"""
import pytest
import numpy as np

from exploration.gravimetry import GravimetryForward, GravimetryInversion

G_CONST = 6.67430e-11
T_M3_TO_KG_M3 = 1000.0


def _sphere_setup():
    NX, NY, NZ, BLOCK = 30, 24, 30, 10.0
    gx, gy, gz = np.mgrid[0:NX, 0:NY, 0:NZ]
    ix = gx.flatten(order="F").astype(np.int32)
    iy = gy.flatten(order="F").astype(np.int32)
    iz = gz.flatten(order="F").astype(np.int32)
    x_c = ix * BLOCK + BLOCK / 2
    y_c = iy * BLOCK + BLOCK / 2
    z_c = iz * BLOCK + BLOCK / 2

    # Esfera: centro profundo, radio pequeño respecto a la distancia a sensores.
    cx, cy, cz, R = 150.0, 180.0, 150.0, 30.0
    delta_rho = 0.6  # t/m³
    r_vox = np.sqrt((x_c - cx) ** 2 + (y_c - cy) ** 2 + (z_c - cz) ** 2)
    contrast = np.where(r_vox <= R, delta_rho, 0.0)

    forward = GravimetryForward(BLOCK, BLOCK, BLOCK, cutoff_radius=5000.0)
    return forward, x_c, y_c, z_c, contrast, (cx, cy, cz, R, delta_rho, BLOCK)


def _analytic_point_mass_gy(sensors, mass_kg, centroid):
    cx, cy, cz = centroid
    g = np.empty(sensors.shape[0])
    for i, (sx, sy, sz) in enumerate(sensors):
        dx, dy, dz = cx - sx, cy - sy, cz - sz
        r = np.sqrt(dx * dx + dy * dy + dz * dz)
        g[i] = G_CONST * mass_kg * dy / (r ** 3)   # componente vertical (y = profundidad)
    return g


@pytest.mark.benchmark
def test_kernel_matches_analytic_point_mass():
    forward, x_c, y_c, z_c, contrast, meta = _sphere_setup()
    cx, cy, cz, R, delta_rho, BLOCK = meta

    sensors = np.array(
        [[150, 0, 150], [100, 0, 150], [200, 0, 150],
         [150, 0, 100], [150, 0, 200], [120, 0, 120]],
        dtype=np.float64,
    )

    kernel = forward.build_sparse_kernel(x_c, y_c, z_c, sensors)
    g_synth = kernel @ contrast

    # Masa REALMENTE discretizada (suma de vóxeles dentro de la esfera) en el centroide.
    vox_vol = BLOCK ** 3
    n_sphere = int(np.sum(contrast > 0))
    mass_kg = n_sphere * vox_vol * delta_rho * T_M3_TO_KG_M3
    # Centroide real de los vóxeles de la esfera (≈ centro geométrico).
    mask = contrast > 0
    centroid = (float(np.mean(x_c[mask])), float(np.mean(y_c[mask])), float(np.mean(z_c[mask])))

    g_analytic = _analytic_point_mass_gy(sensors, mass_kg, centroid)

    rel_err = np.abs(g_synth - g_analytic) / np.abs(g_analytic)
    assert np.all(g_synth > 0), "g_y debe ser positiva (masa por debajo del sensor)"
    assert np.mean(rel_err) < 0.05, f"error relativo medio alto: {np.mean(rel_err):.3%}"
    assert np.max(rel_err) < 0.10, f"error relativo máximo alto: {np.max(rel_err):.3%}"


@pytest.mark.benchmark
def test_inversion_localizes_anomaly_horizontally():
    """El solver debe recuperar la anomalía en la posición HORIZONTAL correcta.
    (La profundidad tiene sesgo ~40% por la no-unicidad gravimétrica — no se exige.)"""
    forward, x_c, y_c, z_c, contrast, meta = _sphere_setup()
    cx, cy, cz, R, delta_rho, BLOCK = meta
    NX, NY, NZ = 30, 24, 30

    # Survey denso en superficie.
    sx, sz = np.meshgrid(
        np.arange(2, NX, 3) * BLOCK + BLOCK / 2,
        np.arange(2, NZ, 3) * BLOCK + BLOCK / 2,
        indexing="ij",
    )
    sensors = np.column_stack([sx.ravel(), np.zeros(sx.size), sz.ravel()]).astype(np.float64)

    kernel = forward.build_sparse_kernel(x_c, y_c, z_c, sensors)
    g_obs = kernel @ contrast

    inv = GravimetryInversion(NX, NY, NZ, BLOCK)
    density, _score, _misfit, _sens = inv.solve_inversion_lsqr(
        g_obs, None, y_c, lambda_mag=1e-3, alpha_spatial=1.0,
        forward_model=forward, sensor_coords=sensors, x_c=x_c, z_c=z_c,
    )
    recovered_contrast = density - inv.base_density
    finite = np.isfinite(recovered_contrast)
    strong = finite & (recovered_contrast > 0.5 * np.nanmax(recovered_contrast))
    # Centro de masa horizontal del cuerpo recuperado.
    cx_rec = np.average(x_c[strong], weights=recovered_contrast[strong])
    cz_rec = np.average(z_c[strong], weights=recovered_contrast[strong])
    assert abs(cx_rec - cx) < 2 * BLOCK, f"X recuperado {cx_rec:.1f} lejos de {cx}"
    assert abs(cz_rec - cz) < 2 * BLOCK, f"Z recuperado {cz_rec:.1f} lejos de {cz}"


@pytest.mark.benchmark
def test_inversion_anti_inverse_crime():
    """Anti-inverse-crime: malla forward ≠ malla de inversión.

    Forward: 30×24×30 @ 10m = 300m³ de lado.
    Inversión: 20×16×20 @ 15m — diferente número de celdas Y diferente block size.

    La anomalía real (esfera en 150,180,150) debe recuperarse en posición horizontal
    correcta a pesar de que las dos mallas son inconmensurables.
    """
    # ── Malla forward (fina, 10m) ───────────────────────────────────────────
    NX_F, NY_F, NZ_F, BS_F = 30, 24, 30, 10.0
    gx, gy, gz = np.mgrid[0:NX_F, 0:NY_F, 0:NZ_F]
    ix_f = gx.flatten(order="F").astype(np.int32)
    iy_f = gy.flatten(order="F").astype(np.int32)
    iz_f = gz.flatten(order="F").astype(np.int32)
    x_f = ix_f * BS_F + BS_F / 2
    y_f = iy_f * BS_F + BS_F / 2
    z_f = iz_f * BS_F + BS_F / 2

    cx, cy, cz, R = 150.0, 150.0, 150.0, 25.0
    delta_rho = 0.6
    r_vox = np.sqrt((x_f - cx)**2 + (y_f - cy)**2 + (z_f - cz)**2)
    contrast_f = np.where(r_vox <= R, delta_rho, 0.0)

    forward_f = GravimetryForward(BS_F, BS_F, BS_F, cutoff_radius=5000.0)

    sensors = np.array(
        [[cx - 60, 0, cz - 60], [cx, 0, cz - 60], [cx + 60, 0, cz - 60],
         [cx - 60, 0, cz],      [cx, 0, cz],       [cx + 60, 0, cz],
         [cx - 60, 0, cz + 60], [cx, 0, cz + 60],  [cx + 60, 0, cz + 60]],
        dtype=np.float64,
    )

    kernel_f = forward_f.build_sparse_kernel(x_f, y_f, z_f, sensors)
    g_obs = kernel_f @ contrast_f

    assert not np.allclose(g_obs, 0.0), "g_obs sintético debe tener señal"
    assert np.isfinite(g_obs).all(), "g_obs no debe tener NaN/Inf"

    # ── Malla de inversión (diferente: 20×16×20 @ 15m) ─────────────────────
    # Esta malla NO coincide con la forward → se elimina el inverse crime.
    NX_I, NY_I, NZ_I, BS_I = 20, 16, 20, 15.0
    gx_i, gy_i, gz_i = np.mgrid[0:NX_I, 0:NY_I, 0:NZ_I]
    x_i = gx_i.flatten(order="F").astype(np.int32) * BS_I + BS_I / 2
    y_i = gy_i.flatten(order="F").astype(np.int32) * BS_I + BS_I / 2
    z_i = gz_i.flatten(order="F").astype(np.int32) * BS_I + BS_I / 2

    inv = GravimetryInversion(NX_I, NY_I, NZ_I, BS_I)
    density, _score, misfit, _sens = inv.solve_inversion_lsqr(
        g_obs, None, y_i,
        lambda_mag=1e-3, alpha_spatial=1.0,
        forward_model=GravimetryForward(BS_I, BS_I, BS_I, cutoff_radius=5000.0),
        sensor_coords=sensors, x_c=x_i, z_c=z_i,
    )

    recovered = density - inv.base_density
    finite_mask = np.isfinite(recovered)
    threshold = 0.4 * np.nanmax(recovered)
    strong = finite_mask & (recovered > threshold)

    assert strong.any(), "El solver no recuperó ninguna anomalía positiva"

    cx_rec = float(np.average(x_i[strong], weights=recovered[strong]))
    cz_rec = float(np.average(z_i[strong], weights=recovered[strong]))

    # Tolerancia más amplia que con misma malla (3 celdas de inversión = 45m)
    assert abs(cx_rec - cx) < 3 * BS_I, (
        f"Posición X recuperada {cx_rec:.1f}m lejos de la verdadera {cx}m "
        f"(tolerancia ±{3 * BS_I}m, malla inversión {BS_I}m ≠ malla forward {BS_F}m)"
    )
    assert abs(cz_rec - cz) < 3 * BS_I, (
        f"Posición Z recuperada {cz_rec:.1f}m lejos de la verdadera {cz}m "
        f"(tolerancia ±{3 * BS_I}m, malla inversión {BS_I}m ≠ malla forward {BS_F}m)"
    )
