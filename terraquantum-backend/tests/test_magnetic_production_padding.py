"""
Producción magnética — padding (BC física) + superficie DEM cableados E2E.
=========================================================================

El motor magnético YA aceptaba padding_mask/hx/hy/hz (test_magnetic_padding.py),
pero el PATH DE PRODUCCIÓN (run_magnetic_inversion → run_geophysics_inversion, el
mismo que usa /load-package) construía la malla CORE pelada sin padding y con
topografía plana → el artefacto de borde de Raglan seguía presente en la app.

Estos tests verifican que producción AHORA:
  1. Construye la malla extendida (nx_total > nx) y resuelve sobre core+padding,
     reportándolo en report.mesh (padding_active, n_padding, n_padding_solved).
  2. Reduce el modelo al CORE: ningún vóxel de salida cae fuera de [0,nx)×[0,nz)
     (el padding cumple su rol de BC y se descarta del modelo reportado).
  3. Aplica la superficie DEM densa cuando se proveen sensor_elevations_masl,
     con fallback seguro a 'flat' cuando no.
  4. Funciona en AMBOS modos: escalar y MVI (vector).

No se tunea ningún umbral: solo se afirma el cableado y la invariancia del contrato.
"""
import os
import sys

import numpy as np

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from exploration.magnetometry import MagnetometryForward

INC, DEC, B0 = -30.0, 2.0, 23500.0
NX, NY, NZ, BLOCK = 6, 8, 6, 20.0


def _make_mag_input(model="scalar", with_elevations=False):
    """Input magnético-aislado (g=0) con TMI sintetizada en la grilla del servicio."""
    from schemas.geophysics_schema import GeophysicsInvertInput, GravityObservation
    from services.geophysics_service import build_voxel_grid

    obs = []
    for i in range(6):
        for j in range(6):
            obs.append(GravityObservation(x_m=10 + i * 20, y_m=0.0, z_m=10 + j * 20, g=0.0))
    sensors = np.array([[o.x_m, o.y_m, o.z_m] for o in obs], dtype=float)

    base = GeophysicsInvertInput(
        project_id=None, run_id=None,
        depth=120, nir=50, fe=30, region="desconocida", lat="-23.5", lon="-70.2",
        nx=NX, ny=NY, nz=NZ, block_size=BLOCK, cutoff_radius=200.0,
        lambda_mag=1e-3, alpha_spatial=1.0,
        observations=obs,
        magnetic_nt=[0.0] * len(obs),
        inclination_deg=INC, declination_deg=DEC, field_intensity_nt=B0,
    )
    ix, iy, iz, x_c, y_c, z_c = build_voxel_grid(base)
    fwd = MagnetometryForward(BLOCK, BLOCK, BLOCK, cutoff_radius=200.0,
                              inclination_deg=INC, declination_deg=DEC, field_intensity_nt=B0)
    G = fwd.build_sparse_kernel(x_c, y_c, z_c, sensors)
    kappa = np.zeros(len(x_c))
    kappa[((x_c - 60) ** 2 + (y_c - 50) ** 2 + (z_c - 60) ** 2) < 25 ** 2] = 0.2
    d = G @ kappa
    update = {"magnetic_nt": d.tolist(), "magnetization_model": model}
    if with_elevations:
        # Elevaciones variables (relieve sintético) → activa la superficie DEM densa.
        elevs = [1000.0 + 0.05 * (o.x_m + o.z_m) for o in obs]
        update["sensor_elevations_masl"] = elevs
    return base.model_copy(update=update)


def _run(inp):
    from services.geophysics_service import run_geophysics_inversion
    return run_geophysics_inversion(inp)


# ─────────────────────────── Padding en producción ────────────────────────────
def test_production_scalar_builds_padding_mesh():
    """El path escalar de producción construye la malla extendida y resuelve con padding."""
    res = _run(_make_mag_input("scalar"))
    mesh = res["report"]["mesh"]
    assert mesh["nx_total"] > NX and mesh["ny_total"] > NY and mesh["nz_total"] > NZ
    assert mesh["n_core"] == NX * NY * NZ
    assert mesh["n_padding"] > 0
    assert mesh["padding_active"] is True
    assert mesh["n_padding_solved"] and mesh["n_padding_solved"] > 0
    assert mesh["padding_kappa"] == 1e5


def test_production_mvi_builds_padding_mesh():
    """El path MVI (vector) de producción también construye+resuelve con padding 3C."""
    res = _run(_make_mag_input("vector"))
    mesh = res["report"]["mesh"]
    assert mesh["nx_total"] > NX
    assert mesh["padding_active"] is True
    assert mesh["n_padding_solved"] and mesh["n_padding_solved"] > 0
    # El contrato MVI se mantiene (dirección por vóxel)
    assert res["report"]["magnetization_model"] == "vector"
    assert "magnetization_inc_deg" in res["voxels"][0]


def test_production_voxels_are_core_only():
    """Las salidas se reducen al CORE: ningún vóxel reportado vive en el padding."""
    res = _run(_make_mag_input("scalar"))
    assert res["voxels"], "no se recuperaron vóxeles"
    for v in res["voxels"]:
        assert 0 <= v["ix"] < NX, f"ix={v['ix']} fuera del core"
        assert 0 <= v["iy"] < NY, f"iy={v['iy']} fuera del core"
        assert 0 <= v["iz"] < NZ, f"iz={v['iz']} fuera del core"
        # Centros dentro del footprint del core (el padding queda fuera)
        assert 0.0 <= v["x_m"] <= NX * BLOCK
        assert 0.0 <= v["z_m"] <= NZ * BLOCK


# ─────────────────────────── Superficie DEM densa ─────────────────────────────
def test_production_dem_surface_applied_when_elevations_present():
    """Con sensor_elevations_masl se activa la superficie DEM densa (no plano)."""
    res = _run(_make_mag_input("scalar", with_elevations=True))
    topo = res["report"]["mesh"]["topography"]
    assert topo.startswith("from_sensor_elevations_masl"), topo


def test_production_dem_fallback_flat_without_elevations():
    """Sin elevaciones, la topografía cae a 'flat' (fallback seguro, sin error)."""
    res = _run(_make_mag_input("scalar", with_elevations=False))
    assert res["report"]["mesh"]["topography"] == "flat"


def test_production_still_localizes_body_with_padding():
    """No-regresión de targeting: el cuerpo interior sigue localizándose con padding."""
    res = _run(_make_mag_input("scalar"))
    bt = res["best_target"]
    assert bt is not None
    # El cuerpo sintético está centrado en (x=60, z=60); el pico debe caer cerca,
    # no clavado en un borde del core (0 o NX*BLOCK).
    assert 20.0 <= bt["x_m"] <= 100.0, f"x={bt['x_m']} sospechoso de borde"
    assert 20.0 <= bt["z_m"] <= 100.0, f"z={bt['z_m']} sospechoso de borde"
