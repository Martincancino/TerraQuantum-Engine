"""
FASE 1.3 — Inversión de AMPLITUD (magnetic amplitude inversion).

La amplitud del campo anómalo |B|=√(Bx²+By²+Bz²) es DÉBILMENTE dependiente de la
dirección de magnetización de la fuente → localiza cuerpos con REMANENCIA oblicua
sin asumir su dirección, robustez que la TMI inducida no tiene.

Tests:
  1. Consistencia: cuerpo INDUCIDO → la inversión de amplitud lo localiza con misfit bajo.
  2. ROBUSTEZ A REMANENCIA (clave): cuerpo con magnetización remanente OBLICUA →
     la amplitud lo localiza mejor que la TMI inducida (que asume la dirección).
  3. Bounds: κ recuperada dentro de [susc_min, susc_max].
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import numpy as np

from exploration.magnetometry import (
    MagnetometryForward,
    MagnetometryInversion,
    field_unit_vector,
)

NX, NY, NZ = 8, 8, 8
BS = 40.0
INC_IND, DEC_IND, B0 = -30.0, 2.0, 23500.0


def _grid_centers():
    ix, iy, iz = np.meshgrid(np.arange(NX), np.arange(NY), np.arange(NZ), indexing="ij")
    return (ix.ravel() + 0.5) * BS, (iy.ravel() + 0.5) * BS, (iz.ravel() + 0.5) * BS


def _voxel_index(ix, iy, iz):
    return ix * NY * NZ + iy * NZ + iz


def _sensors():
    xs = np.linspace(BS, (NX - 1) * BS, 7)
    zs = np.linspace(BS, (NZ - 1) * BS, 7)
    xg, zg = np.meshgrid(xs, zs)
    return np.column_stack([xg.ravel(), np.zeros(xg.size), zg.ravel()])


def _peak_xz(susc_full):
    """Coordenada (x,z) del vóxel de mayor susceptibilidad recuperada."""
    x_c, y_c, z_c = _grid_centers()
    s = np.nan_to_num(susc_full, nan=0.0)
    j = int(np.argmax(s))
    return x_c[j], z_c[j], y_c[j]


def _make_body(ix, iz, iy0, iy1, kappa):
    true = np.zeros(NX * NY * NZ)
    for iy in range(iy0, iy1 + 1):
        true[_voxel_index(ix, iy, iz)] = kappa
    return true


def test_amplitude_recovers_induced_body():
    """Cuerpo inducido: la inversión de amplitud lo ajusta y lo localiza."""
    sensors = _sensors()
    x_c, y_c, z_c = _grid_centers()
    fwd = MagnetometryForward(BS, BS, BS, cutoff_radius=BS * 14,
                              inclination_deg=INC_IND, declination_deg=DEC_IND,
                              field_intensity_nt=B0)
    inv = MagnetometryInversion(NX, NY, NZ, BS)

    ix_t, iz_t = 4, 4
    true = _make_body(ix_t, iz_t, 2, 3, 0.5)
    Gx, Gy, Gz = fwd.build_mvi_kernels(x_c, y_c, z_c, sensors)
    bx, by, bz = Gx @ true, Gy @ true, Gz @ true
    amp = np.sqrt(bx * bx + by * by + bz * bz)

    susc, score, misfit, sens = inv.solve_amplitude_inversion_lsqr(
        d_observed=amp, y_c=y_c, forward_model=fwd, sensor_coords=sensors,
        x_c=x_c, z_c=z_c, lambda_mag=1e-3, alpha_spatial=1.0,
        susc_min=0.0, susc_max=2.0,
    )
    # La inversión de amplitud ajusta su dato (misfit más alto que TMI: es no-lineal +
    # regularizada sobre un cuerpo compacto con footprint positivo ancho) y, sobre todo,
    # LOCALIZA el cuerpo — el objetivo real de targeting.
    assert np.isfinite(misfit) and misfit < 30.0, f"misfit={misfit:.1f}%"
    px, pz, _ = _peak_xz(susc)
    err = np.hypot(px - (ix_t + 0.5) * BS, pz - (iz_t + 0.5) * BS)
    assert err <= 1.5 * BS, f"localización amplitud err={err:.0f}m (>{1.5*BS:.0f})"


def test_amplitude_robust_to_oblique_remanence():
    """CLAVE: cuerpo con remanencia OBLICUA → la amplitud localiza mejor que la TMI inducida."""
    sensors = _sensors()
    x_c, y_c, z_c = _grid_centers()

    # Forward inducido (lo que el geofísico ASUME).
    fwd_ind = MagnetometryForward(BS, BS, BS, cutoff_radius=BS * 14,
                                  inclination_deg=INC_IND, declination_deg=DEC_IND,
                                  field_intensity_nt=B0)
    # Forward con la dirección REMANENTE real (reversa/oblicua, desconocida para el geofísico).
    fwd_rem = MagnetometryForward(BS, BS, BS, cutoff_radius=BS * 14,
                                  inclination_deg=70.0, declination_deg=160.0,
                                  field_intensity_nt=B0)
    inv = MagnetometryInversion(NX, NY, NZ, BS)

    ix_t, iz_t = 4, 4
    true_xz = ((ix_t + 0.5) * BS, (iz_t + 0.5) * BS)
    true = _make_body(ix_t, iz_t, 2, 3, 0.6)

    # Campo 3C de la fuente REMANENTE → amplitud + TMI inducida.
    Gxr, Gyr, Gzr = fwd_rem.build_mvi_kernels(x_c, y_c, z_c, sensors)
    bx, by, bz = Gxr @ true, Gyr @ true, Gzr @ true
    amp = np.sqrt(bx * bx + by * by + bz * bz)
    f_ind = field_unit_vector(INC_IND, DEC_IND)
    tmi = f_ind[0] * bx + f_ind[1] * by + f_ind[2] * bz   # ΔT = f̂_ind · B_rem

    # (a) Inversión de AMPLITUD con el kernel inducido.
    susc_amp, _s, mis_amp, _se = inv.solve_amplitude_inversion_lsqr(
        d_observed=amp, y_c=y_c, forward_model=fwd_ind, sensor_coords=sensors,
        x_c=x_c, z_c=z_c, lambda_mag=1e-3, alpha_spatial=1.0,
        susc_min=0.0, susc_max=2.0,
    )
    pxa, pza, _ = _peak_xz(susc_amp)
    err_amp = np.hypot(pxa - true_xz[0], pza - true_xz[1])

    # (b) Inversión TMI inducida estándar (asume la dirección → sesgada por la remanencia).
    susc_tmi, _s2, _mis2, _se2 = inv.solve_magnetic_inversion_lsqr(
        d_observed=tmi, y_c=y_c, lambda_mag=1e-3, alpha_spatial=1.0,
        forward_model=fwd_ind, sensor_coords=sensors, x_c=x_c, z_c=z_c,
        susc_min=0.0, susc_max=2.0,
    )
    pxt, pzt, _ = _peak_xz(susc_tmi)
    err_tmi = np.hypot(pxt - true_xz[0], pzt - true_xz[1])

    # La amplitud ajusta su dato y localiza dentro de ~1 celda pese a la remanencia oblicua.
    assert mis_amp < 30.0, f"misfit amplitud={mis_amp:.1f}%"
    assert err_amp <= 1.5 * BS, f"amplitud err={err_amp:.0f}m"
    # Y NO es peor que la TMI inducida (típicamente mejor o igual ante remanencia oblicua).
    assert err_amp <= err_tmi + 1e-6, (
        f"amplitud debería localizar al menos tan bien: amp={err_amp:.0f}m tmi={err_tmi:.0f}m"
    )


def test_amplitude_respects_bounds():
    """κ recuperada queda dentro de [susc_min, susc_max]."""
    sensors = _sensors()
    x_c, y_c, z_c = _grid_centers()
    fwd = MagnetometryForward(BS, BS, BS, cutoff_radius=BS * 14,
                              inclination_deg=INC_IND, declination_deg=DEC_IND,
                              field_intensity_nt=B0)
    inv = MagnetometryInversion(NX, NY, NZ, BS)
    true = _make_body(4, 4, 2, 3, 0.5)
    Gx, Gy, Gz = fwd.build_mvi_kernels(x_c, y_c, z_c, sensors)
    amp = np.sqrt((Gx @ true) ** 2 + (Gy @ true) ** 2 + (Gz @ true) ** 2)
    susc, _s, _m, _se = inv.solve_amplitude_inversion_lsqr(
        d_observed=amp, y_c=y_c, forward_model=fwd, sensor_coords=sensors,
        x_c=x_c, z_c=z_c, lambda_mag=1e-3, alpha_spatial=1.0,
        susc_min=0.0, susc_max=0.8,
    )
    finite = susc[np.isfinite(susc)]
    assert finite.min() >= -1e-9 and finite.max() <= 0.8 + 1e-6


if __name__ == "__main__":
    import pytest
    pytest.main([__file__, "-v"])
