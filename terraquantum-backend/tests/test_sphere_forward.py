"""
Fase 5, §5.4 Test 1 — Verifica kernel Gz (Nagy 1966) contra solución analítica de esfera.

Para una esfera uniforme evaluada en un punto EXTERNO, la gravedad vertical es
idéntica a la de una masa puntual concentrada en su centro (teorema de la cáscara):

    gz = G * M / r²  (componente vertical: G * M * Δy / r³)

La fórmula exacta del Plan Industrial Tier 1 §5.4:

    gz_exact = G * V_sphere * rho * D / (D² + D²)^{3/2}

corresponde al sensor en (cx+D, 0, cz) con la esfera centrada en (cx, D, cz):
    Δx = D  (desplazamiento horizontal),  Δy = D  (profundidad del centro)
    r   = sqrt(D² + D²) = D√2

Parámetros exactos del plan §5.4:
    R = 100 m, D = 500 m, rho_contrast = 0.5 t/m³ (= 500 kg/m³)

Criterio de aceptación §5.5 ítem 1: error relativo < 5% en norma L2.
"""
import numpy as np
import pytest

from exploration.gravimetry import GravimetryForward

G_CONST = 6.67430e-11   # m³ / (kg · s²) — CODATA 2014


@pytest.mark.benchmark
def test_sphere_forward():
    """
    §5.4 Test 1 — kernel Nagy reproduce <5% del valor analítico de esfera.

    Configuración: sensor a distancia horizontal D del centro, esfera a profundidad D.
    La distancia sensor-centro es r = D√2, por lo que:

        gz_exact = G · V · ρ · D / (D² + D²)^{3/2}

    Para R/r = 100/707 = 0.14, el error multipolar teórico es ≈ (R/r)² < 2 %.
    """
    # ── Parámetros exactos §5.4 ──────────────────────────────────────────────
    R       = 100.0   # m — radio esfera
    D       = 500.0   # m — profundidad del centro = desplazamiento horizontal del sensor
    rho_kg  = 500.0   # kg/m³ — contraste (= 0.5 t/m³)

    V_sphere = (4.0 / 3.0) * np.pi * R ** 3          # m³
    gz_exact = G_CONST * V_sphere * rho_kg * D / (D ** 2 + D ** 2) ** 1.5   # m/s²

    # ── Grilla de vóxeles 20 m (R/bs = 5 → buena discretización de la esfera)
    BS = 20.0
    NX, NY, NZ = 21, 32, 16    # dominio: 420 × 640 × 320 m
    ix_g, iy_g, iz_g = np.mgrid[0:NX, 0:NY, 0:NZ]
    x_c = ix_g.flatten(order="F") * BS + BS / 2.0
    y_c = iy_g.flatten(order="F") * BS + BS / 2.0
    z_c = iz_g.flatten(order="F") * BS + BS / 2.0

    # Esfera centrada en (cx, D, cz) — enteramente dentro del dominio
    cx, cy, cz = 210.0, D, 150.0
    r_vox = np.sqrt((x_c - cx) ** 2 + (y_c - cy) ** 2 + (z_c - cz) ** 2)

    rho_contrast_t_m3 = rho_kg / 1000.0    # conversión: kg/m³ → t/m³
    model = np.where(r_vox <= R, rho_contrast_t_m3, 0.0)

    n_sphere = int(np.sum(model > 0))
    assert n_sphere > 0, (
        f"La esfera no contiene ningún vóxel (BS={BS}m, R={R}m, "
        f"centro=({cx},{cy},{cz})). Ajustar parámetros de grilla."
    )

    # ── Sensor exactamente a (cx+D, 0, cz) → Δx=D, Δy=D, r=D√2 ─────────────
    sensor = np.array([[cx + D, 0.0, cz]], dtype=np.float64)

    # ── Forward kernel ────────────────────────────────────────────────────────
    # cutoff_radius >> D√2=707m → todas las celdas de la esfera contribuyen
    forward = GravimetryForward(BS, BS, BS, cutoff_radius=10000.0)
    kernel  = forward.build_sparse_kernel(x_c, y_c, z_c, sensor)
    gz_modeled = float((kernel @ model)[0])

    rel_err = abs(gz_modeled - gz_exact) / abs(gz_exact)

    assert gz_modeled > 0, (
        f"gz_modeled={gz_modeled:.4e} debe ser positivo "
        f"(la esfera está por debajo del sensor, y=profundidad)."
    )
    assert rel_err < 0.05, (
        f"Kernel Nagy §5.4: error relativo = {rel_err:.2%} > 5%. "
        f"gz_modeled = {gz_modeled:.6e} m/s² | gz_exact = {gz_exact:.6e} m/s². "
        f"N_sphere_voxels = {n_sphere} (BS={BS}m, R={R}m, D={D}m). "
        "El kernel no reproduce la solución analítica de esfera."
    )


@pytest.mark.benchmark
def test_sphere_forward_l2_norm():
    """
    §5.5 criterio 1: error < 5% en norma L2 (múltiples sensores).

    Construye 7 sensores a distintas posiciones horizontales y verifica que
    el error L2 (norma relativa) del vector de observaciones es < 5%.
    Esto detecta errores sistemáticos de signo o escala que el test puntual podría perder.
    """
    R, rho_kg = 100.0, 500.0
    D = 500.0
    rho_t = rho_kg / 1000.0
    V_sphere = (4.0 / 3.0) * np.pi * R ** 3

    BS = 20.0
    NX, NY, NZ = 21, 32, 16
    ix_g, iy_g, iz_g = np.mgrid[0:NX, 0:NY, 0:NZ]
    x_c = ix_g.flatten(order="F") * BS + BS / 2.0
    y_c = iy_g.flatten(order="F") * BS + BS / 2.0
    z_c = iz_g.flatten(order="F") * BS + BS / 2.0

    cx, cy, cz = 210.0, D, 150.0
    r_vox = np.sqrt((x_c - cx) ** 2 + (y_c - cy) ** 2 + (z_c - cz) ** 2)
    model = np.where(r_vox <= R, rho_t, 0.0)

    # 7 sensores a distintas distancias horizontales en X (al nivel de cz)
    offsets_x = np.array([-600, -400, -200, 0, 200, 400, 600], dtype=float)
    sensors = np.column_stack([
        np.full(7, cx) + offsets_x,
        np.zeros(7),
        np.full(7, cz),
    ])

    forward = GravimetryForward(BS, BS, BS, cutoff_radius=10000.0)
    kernel  = forward.build_sparse_kernel(x_c, y_c, z_c, sensors)
    gz_modeled = kernel @ model

    # Analítico: point-mass en el centroide verdadero de los vóxeles
    mask = model > 0
    centroid_x = float(np.average(x_c[mask], weights=model[mask]))
    centroid_y = float(np.average(y_c[mask], weights=model[mask]))
    centroid_z = float(np.average(z_c[mask], weights=model[mask]))
    M_kg = float(np.sum(model[mask])) * (BS ** 3) * 1000.0   # t/m³→kg/m³, ×vol

    gz_analytic = np.empty(len(sensors))
    for i, (sx, sy, sz) in enumerate(sensors):
        dy = centroid_y - sy
        r  = np.sqrt((centroid_x - sx) ** 2 + dy ** 2 + (centroid_z - sz) ** 2)
        gz_analytic[i] = G_CONST * M_kg * dy / r ** 3

    l2_rel = float(np.linalg.norm(gz_modeled - gz_analytic) / np.linalg.norm(gz_analytic))

    assert l2_rel < 0.05, (
        f"Error L2 relativo = {l2_rel:.2%} > 5% (§5.5 criterio 1). "
        f"gz_modeled_rms = {np.sqrt(np.mean(gz_modeled**2)):.4e} | "
        f"gz_analytic_rms = {np.sqrt(np.mean(gz_analytic**2)):.4e}"
    )


# ── Ejecución directa ────────────────────────────────────────────────────────

if __name__ == "__main__":
    import traceback

    tests = [test_sphere_forward, test_sphere_forward_l2_norm]
    passed = failed = 0
    for t in tests:
        try:
            t()
            print(f"  PASS  {t.__name__}")
            passed += 1
        except Exception:
            print(f"  FAIL  {t.__name__}")
            traceback.print_exc()
            failed += 1
    print(f"\n{'='*55}")
    print(f"test_sphere_forward — {passed} PASS / {failed} FAIL")
    if failed:
        import sys; sys.exit(1)
