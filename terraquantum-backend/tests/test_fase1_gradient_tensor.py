"""
FASE 1.4 — Tensor de gradiente magnético (gradiometría / FTG).

La gradiometría mide ∂B_i/∂x_j (nT/m): mayor resolución, sin remoción regional ni
deriva de base. El tensor es simétrico y SIN TRAZA (∇·B=0).

Tests:
  1. Diferencias finitas: el gradiente ANALÍTICO = derivada numérica del campo 3C (MVI).
  2. Sin traza: G_xx + G_yy + G_zz ≈ 0 (consistencia física, ∇·B=0).
  3. Inversión: roundtrip de datos (el modelo recuperado reproduce el tensor) + bounds.

LIMITACIÓN HONESTA (MEDIDA): el TARGETING (localización) de la inversión de gradiente
NO es robusto con la maquinaria actual. El kernel del tensor decae como 1/r⁴ (una
potencia más que el campo 1/r³), de modo que el depth weighting (depth+z0)^(β/2)
calibrado para el campo (β=1.5) no transfiere; un barrido sobre 4 cuerpos × β∈{3.5,4,4.5,5}
mostró óptimos DISPERSOS (un cuerpo falla a todos los β). El targeting robusto requiere
depth/sensitivity weighting DEDICADO al gradiente (diferido). Por eso aquí se valida la
física del tensor (FD + sin traza, exactas) y la consistencia de datos de la inversión,
NO una localización que no es fiable. NO se tuneó β para fingir un PASS.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import numpy as np

from exploration.magnetometry import MagnetometryForward, MagnetometryInversion

BS = 40.0
INC, DEC, B0 = -30.0, 2.0, 23500.0


def _fwd():
    # cutoff 800m cubre de sobra la malla de prueba (≈320m) — kernel disperso y rápido.
    return MagnetometryForward(BS, BS, BS, cutoff_radius=800.0,
                               inclination_deg=INC, declination_deg=DEC,
                               field_intensity_nt=B0)


def _field_components(fwd, cell, sensors):
    """Bx,By,Bz (nT por unidad κ) de UNA celda en los sensores dados."""
    cx, cy, cz = cell
    Gx, Gy, Gz = fwd.build_mvi_kernels(
        np.array([cx]), np.array([cy]), np.array([cz]), sensors)
    return Gx.toarray().ravel(), Gy.toarray().ravel(), Gz.toarray().ravel()


def test_gradient_matches_finite_difference():
    """El tensor analítico coincide con la derivada numérica del campo 3C."""
    fwd = _fwd()
    cell = (200.0, 160.0, 220.0)
    sensors = np.array([[100.0, 0.0, 120.0], [260.0, 0.0, 300.0], [180.0, 0.0, 60.0]])
    G = fwd.build_gradient_tensor_kernels(
        np.array([cell[0]]), np.array([cell[1]]), np.array([cell[2]]), sensors)

    h = 0.5
    comp_field = {"x": 0, "y": 1, "z": 2}
    # (componente del tensor, componente de campo i, eje de derivada j)
    checks = [("xx", "x", 0), ("xy", "x", 1), ("xz", "x", 2),
              ("yy", "y", 1), ("yz", "y", 2), ("zz", "z", 2)]
    for comp, fi, j in checks:
        sp_p = sensors.copy(); sp_p[:, j] += h
        sp_m = sensors.copy(); sp_m[:, j] -= h
        bi_p = _field_components(fwd, cell, sp_p)[comp_field[fi]]
        bi_m = _field_components(fwd, cell, sp_m)[comp_field[fi]]
        fd = (bi_p - bi_m) / (2.0 * h)
        ana = G[comp].toarray().ravel()
        denom = np.maximum(np.abs(fd), 1e-12)
        rel = np.max(np.abs(ana - fd) / denom)
        assert rel < 1e-3, f"componente {comp}: rel_err={rel:.2e} ana={ana} fd={fd}"


def test_gradient_tensor_is_traceless():
    """∇·B = 0 ⇒ G_xx + G_yy + G_zz = 0 en todo sensor/celda."""
    fwd = _fwd()
    xc = np.array([200.0, 250.0, 120.0])
    yc = np.array([160.0, 200.0, 240.0])
    zc = np.array([220.0, 100.0, 180.0])
    sensors = np.array([[100.0, 0.0, 120.0], [300.0, 0.0, 260.0]])
    G = fwd.build_gradient_tensor_kernels(xc, yc, zc, sensors)
    trace = (G["xx"] + G["yy"] + G["zz"]).toarray()
    scale = np.abs(G["xx"].toarray()).max()
    assert np.max(np.abs(trace)) < 1e-9 * max(scale, 1e-30), "el tensor debe ser sin traza"


def test_gradient_inversion_data_consistency_and_bounds():
    """La inversión de gradiente corre, respeta bounds y reproduce el dato del tensor.

    NO se asierta localización: el targeting de gradiente no es robusto con el depth
    weighting del campo (ver LIMITACIÓN HONESTA en el docstring del módulo). Sí se
    valida que el modelo recuperado reproduce los datos del tensor (consistencia) y
    queda dentro de bounds — la parte de la inversión que SÍ es fiable.
    """
    NX = NY = NZ = 8
    ix2, iy2, iz2 = np.meshgrid(np.arange(NX), np.arange(NY), np.arange(NZ), indexing="ij")
    x_c = (ix2.ravel() + 0.5) * BS
    y_c = (iy2.ravel() + 0.5) * BS
    z_c = (iz2.ravel() + 0.5) * BS

    def vi(a, b, c):
        return a * NY * NZ + b * NZ + c

    xs = np.linspace(BS, (NX - 1) * BS, 7)
    zs = np.linspace(BS, (NZ - 1) * BS, 7)
    xg, zg = np.meshgrid(xs, zs)
    sensors = np.column_stack([xg.ravel(), np.zeros(xg.size), zg.ravel()])

    fwd = _fwd()
    inv = MagnetometryInversion(NX, NY, NZ, BS)
    true = np.zeros(NX * NY * NZ)
    for iy in (2, 3):
        true[vi(4, iy, 4)] = 0.5

    kernels = fwd.build_gradient_tensor_kernels(x_c, y_c, z_c, sensors)
    comps = ["xx", "xy", "xz", "yy", "yz"]
    tensor_data = {c: kernels[c] @ true for c in comps}

    susc, score, misfit, sens = inv.solve_gradient_tensor_inversion_lsqr(
        tensor_data=tensor_data, components=comps, y_c=y_c,
        forward_model=fwd, sensor_coords=sensors, x_c=x_c, z_c=z_c,
        lambda_mag=1e-3, alpha_spatial=1.0, susc_min=0.0, susc_max=2.0,
        depth_beta=4.5,
    )
    # Bounds + finitud (parte fiable).
    finite = susc[np.isfinite(susc)]
    assert finite.size > 0 and finite.min() >= -1e-9 and finite.max() <= 2.0 + 1e-6
    assert np.isfinite(misfit)

    # Consistencia de datos: el modelo recuperado reproduce el tensor observado.
    rec = np.nan_to_num(susc, nan=0.0)
    num = den = 0.0
    for c in comps:
        pred = kernels[c] @ rec
        num += float(np.sum((pred - tensor_data[c]) ** 2))
        den += float(np.sum(tensor_data[c] ** 2))
    data_rel = np.sqrt(num / max(den, 1e-30))
    assert data_rel < 0.30, f"el modelo recuperado debe reproducir el tensor (rel={data_rel:.2f})"


if __name__ == "__main__":
    import pytest
    pytest.main([__file__, "-v"])
