"""
FASE 1.1 — Validación del kernel de PRISMA magnético (Bhattacharyya/Sharma).

El motor magnético usaba dipolo puro a TODA distancia. El prisma exacto corrige
el sesgo de amplitud en campo cercano (sensor a pocas anchuras de celda). Esta
suite valida el prisma SIN confiar en los signos analíticos del tensor:

  1. CAMPO LEJANO: el prisma converge EXACTAMENTE al dipolo (prueba de signo/escala).
  2. CAMPO CERCANO: el prisma coincide con una integración numérica de sub-dipolos
     (ground-truth independiente), mientras que el dipolo puro SE DESVÍA.
  3. INTEGRACIÓN: el modo "dipole" del forward es byte-idéntico al histórico y el
     modo "prism" solo cambia las columnas de celdas en campo cercano.
"""

import numpy as np
import pytest

from exploration.magnetometry import MagnetometryForward, field_unit_vector

INC, DEC, B0 = -30.0, 2.0, 23500.0
F_HAT = field_unit_vector(INC, DEC)


def _dipole_tmi(cx, cy, cz, sx, sy, sz, volume):
    """Anomalía TMI por unidad de κ de un dipolo puntual (cell_center − sensor)."""
    rvec = np.array([cx - sx, cy - sy, cz - sz], dtype=np.float64)
    r2 = float(rvec @ rvec)
    fdot = float(F_HAT @ rvec)
    C = B0 * volume / (4.0 * np.pi)
    return C * (3.0 * fdot * fdot - r2) / r2 ** 2.5


def _subdipole_tmi(cx, cy, cz, dx, dy, dz, sx, sy, sz, K=24):
    """Ground-truth del prisma: suma de K³ sub-dipolos (converge al prisma real)."""
    ax = cx + (np.arange(K) + 0.5) / K * dx - dx / 2.0
    ay = cy + (np.arange(K) + 0.5) / K * dy - dy / 2.0
    az = cz + (np.arange(K) + 0.5) / K * dz - dz / 2.0
    PX, PY, PZ = np.meshgrid(ax, ay, az, indexing="ij")
    dxv = PX.ravel() - sx
    dyv = PY.ravel() - sy
    dzv = PZ.ravel() - sz
    r2 = dxv * dxv + dyv * dyv + dzv * dzv
    fdot = F_HAT[0] * dxv + F_HAT[1] * dyv + F_HAT[2] * dzv
    v_sub = (dx * dy * dz) / K ** 3
    C_sub = B0 * v_sub / (4.0 * np.pi)
    return float(np.sum(C_sub * (3.0 * fdot * fdot - r2) / r2 ** 2.5))


def _prism_closed(cx, cy, cz, dx, dy, dz, sx, sy, sz):
    D = B0 / (4.0 * np.pi)
    return float(
        MagnetometryForward._magnetic_prism_kernel(
            np.array([cx - sx]), np.array([cy - sy]), np.array([cz - sz]),
            dx, dy, dz, F_HAT, D,
        )[0]
    )


def test_prism_converges_to_dipole_in_far_field():
    """A r ≫ a_eq el prisma y el dipolo coinciden: valida signo y escala del tensor."""
    dx = dy = dz = 50.0
    vol = dx * dy * dz
    sx, sy, sz = 0.0, 0.0, 0.0
    # Celda muy profunda (r ≈ 1500 m, r/a_eq ≈ 17): régimen dipolar.
    cx, cy, cz = 120.0, 1500.0, 80.0
    dip = _dipole_tmi(cx, cy, cz, sx, sy, sz, vol)
    pri = _prism_closed(cx, cy, cz, dx, dy, dz, sx, sy, sz)
    assert abs(pri - dip) / abs(dip) < 1e-3, f"prism={pri} dipole={dip}"


def test_prism_matches_subdipole_in_near_field():
    """En campo cercano el prisma exacto = integración de sub-dipolos (ground-truth)."""
    dx = dy = dz = 50.0
    sx, sy, sz = 0.0, 0.0, 0.0
    # Celda somera centrada bajo el sensor (r=70 m, r/a_eq≈0.8): campo cercano fuerte.
    cx, cy, cz = 10.0, 70.0, 10.0
    truth = _subdipole_tmi(cx, cy, cz, dx, dy, dz, sx, sy, sz, K=32)
    pri = _prism_closed(cx, cy, cz, dx, dy, dz, sx, sy, sz)
    rel = abs(pri - truth) / abs(truth)
    assert rel < 1e-2, f"prism={pri} truth={truth} rel={rel:.4f}"


def test_dipole_is_biased_in_near_field():
    """El dipolo puro SE DESVÍA del ground-truth en campo cercano; el prisma NO.

    Cuantifica el sesgo de amplitud que motiva la Fase 1.1.
    """
    dx = dy = dz = 50.0
    vol = dx * dy * dz
    sx, sy, sz = 0.0, 0.0, 0.0
    cx, cy, cz = 5.0, 60.0, 5.0  # r=60.4 m, r/a_eq≈0.70
    truth = _subdipole_tmi(cx, cy, cz, dx, dy, dz, sx, sy, sz, K=32)
    pri = _prism_closed(cx, cy, cz, dx, dy, dz, sx, sy, sz)
    dip = _dipole_tmi(cx, cy, cz, sx, sy, sz, vol)

    err_prism = abs(pri - truth) / abs(truth)
    err_dipole = abs(dip - truth) / abs(truth)
    # El prisma reproduce el ground-truth; el dipolo no.
    assert err_prism < 0.02, f"prism err={err_prism:.3f}"
    assert err_dipole > 0.05, f"dipole err={err_dipole:.3f} (esperado sesgo notable)"
    assert err_dipole > 3.0 * err_prism, (
        f"el prisma debe ser claramente mejor: dipolo={err_dipole:.3f} prisma={err_prism:.3f}"
    )


def test_forward_dipole_mode_is_unchanged_and_prism_differs_only_near():
    """El modo 'dipole' es el histórico; 'prism' solo altera columnas en campo cercano."""
    BS = 50.0
    cutoff = BS * 20
    # Malla de celdas: una columna de profundidades bajo el sensor + celdas lejanas.
    xs, ys, zs = [], [], []
    for depth in [60.0, 120.0, 300.0, 1000.0]:
        xs.append(0.0); ys.append(depth); zs.append(0.0)
    x_c = np.array(xs); y_c = np.array(ys); z_c = np.array(zs)
    sensors = np.array([[0.0, 0.0, 0.0], [60.0, 0.0, 40.0]])

    fwd_dip = MagnetometryForward(BS, BS, BS, cutoff_radius=cutoff,
                                  inclination_deg=INC, declination_deg=DEC,
                                  field_intensity_nt=B0, near_field_mode="dipole")
    fwd_pri = MagnetometryForward(BS, BS, BS, cutoff_radius=cutoff,
                                  inclination_deg=INC, declination_deg=DEC,
                                  field_intensity_nt=B0, near_field_mode="prism")
    G_dip = fwd_dip._build_sparse_kernel(x_c, y_c, z_c, sensors).toarray()
    G_pri = fwd_pri._build_sparse_kernel(x_c, y_c, z_c, sensors).toarray()

    a_eq = np.sqrt(3.0) * BS
    near_thr = 4.0 * a_eq
    # Para cada celda, distancia mínima a un sensor.
    for j, depth in enumerate([60.0, 120.0, 300.0, 1000.0]):
        rmin = min(
            np.sqrt((x_c[j] - s[0]) ** 2 + (y_c[j] - s[1]) ** 2 + (z_c[j] - s[2]) ** 2)
            for s in sensors
        )
        col_rel = np.max(np.abs(G_pri[:, j] - G_dip[:, j])) / (np.max(np.abs(G_dip[:, j])) + 1e-30)
        if rmin <= near_thr:
            # Celda en campo cercano: el prisma se aplica → difiere del dipolo (más
            # cerca, mayor diferencia; en el borde r≈4·a_eq la diferencia es pequeña).
            assert col_rel > 1e-4, f"celda cercana depth={depth} debería cambiar (rel={col_rel:.2e})"
        else:
            # Celda lejana: mismo camino dipolar → byte-idéntico.
            assert col_rel < 1e-9, f"celda lejana depth={depth} no debería cambiar (rel={col_rel:.2e})"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
