"""
Track 4 / T4.1 — Validación formal del kernel gravimétrico contra solución analítica.

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
