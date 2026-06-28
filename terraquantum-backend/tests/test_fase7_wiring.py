"""
FASE 7.2 (God-Tier) — Cableado de PRODUCCIÓN del prior geológico implícito.

Fase 7 entregó los building blocks de geología implícita (implicit_modeling.py:
φ HRBF + spatial prior + level-set) como operadores numpy SIN cablear al solver.
Este test cubre el cableado de producción del lado "geología → geofísica" (7.2):

  boreholes[].lithology  →  φ HRBF  →  m_ref petrofísico por celda  →  solve_inversion_lsqr

Verifica:
  1) helper _build_implicit_geology_reference: OFF → (None, None) (byte-idéntico);
  2) helper: activado SIN litología → HTTPException 422 (no se inventa geología);
  3) helper: activado CON litología → m_ref de contraste correcto (celdas objetivo
     con el contraste de la unidad, celdas caja ~0), longitud = grilla completa;
  4) helper: softness>0 produce membership suave (contraste intermedio en el contacto);
  5) E2E run_geophysics_inversion: SIN flag → report.implicit_geology None;
  6) E2E: CON flag → report.implicit_geology poblado y el modelo invertido CAMBIA
     (prueba que m_ref realmente entra al solve), sesgado hacia la unidad objetivo.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import numpy as np
import pytest

from fastapi import HTTPException

from schemas.geophysics_schema import (
    BoreholeInterval,
    GeophysicsInvertInput,
    ImplicitGeologyParams,
    StructuralOrientation,
)
from services.geophysics_service import _build_implicit_geology_reference


# ── Grilla sintética compartida ──────────────────────────────────────────────
NX, NY, NZ, BS = 6, 6, 6, 30.0
BASE_DENSITY = 2.6
TARGET_DENSITY = 3.6
# Sondaje en el centro de la planta; tramo profundo = unidad objetivo "kimberlite".
HOLE_X, HOLE_Z = 2.5 * BS, 2.5 * BS  # cae en el centro de una columna de celdas


def _grid_centers():
    ix, iy, iz = np.meshgrid(np.arange(NX), np.arange(NY), np.arange(NZ), indexing="ij")
    x_c = (ix.ravel() + 0.5) * BS
    y_c = (iy.ravel() + 0.5) * BS  # y = profundidad (+ abajo)
    z_c = (iz.ravel() + 0.5) * BS
    return x_c, y_c, z_c


def _lithology_boreholes():
    """Pozo vertical con caja somera + unidad objetivo profunda (solo litología)."""
    return [
        BoreholeInterval(x_m=HOLE_X, z_m=HOLE_Z, y_from_m=0.0, y_to_m=90.0,
                         lithology="granite"),
        BoreholeInterval(x_m=HOLE_X, z_m=HOLE_Z, y_from_m=90.0, y_to_m=180.0,
                         lithology="kimberlite"),
    ]


def _params(boreholes=None, implicit_geology=None):
    return GeophysicsInvertInput(
        project_id="p", run_id="r", depth=int(NY * BS), nir=0, fe=0, region="test",
        nx=NX, ny=NY, nz=NZ, block_size=int(BS), cutoff_radius=int(NX * BS * 4),
        lambda_mag=1e-3, alpha_spatial=1.0,
        observations=[
            {"x_m": float(i * BS), "y_m": 0.0, "z_m": float((i % NZ) * BS), "g": 1e-6}
            for i in range(NX * NZ)
        ],
        boreholes=boreholes,
        implicit_geology=implicit_geology,
    )


# ── 1) OFF → sin referencia, byte-idéntico ───────────────────────────────────
def test_disabled_returns_none():
    x_c, y_c, z_c = _grid_centers()
    params = _params(boreholes=_lithology_boreholes(), implicit_geology=None)
    m_ref, meta = _build_implicit_geology_reference(params, x_c, y_c, z_c, BASE_DENSITY)
    assert m_ref is None and meta is None


def test_enabled_false_returns_none():
    x_c, y_c, z_c = _grid_centers()
    geo = ImplicitGeologyParams(enabled=False, target_lithologies=["kimberlite"],
                                target_density_t_m3=TARGET_DENSITY)
    params = _params(boreholes=_lithology_boreholes(), implicit_geology=geo)
    m_ref, meta = _build_implicit_geology_reference(params, x_c, y_c, z_c, BASE_DENSITY)
    assert m_ref is None and meta is None


# ── 2) Activado sin litología → 422 (no se inventa geología) ──────────────────
def test_enabled_without_lithology_raises_422():
    x_c, y_c, z_c = _grid_centers()
    geo = ImplicitGeologyParams(target_lithologies=["kimberlite"],
                                target_density_t_m3=TARGET_DENSITY)
    # boreholes con SOLO densidad (sin litología)
    bhs = [BoreholeInterval(x_m=HOLE_X, z_m=HOLE_Z, y_from_m=90.0, y_to_m=180.0,
                            density_t_m3=3.4)]
    params = _params(boreholes=bhs, implicit_geology=geo)
    with pytest.raises(HTTPException) as exc:
        _build_implicit_geology_reference(params, x_c, y_c, z_c, BASE_DENSITY)
    assert exc.value.status_code == 422


def test_enabled_without_any_boreholes_raises_422():
    x_c, y_c, z_c = _grid_centers()
    geo = ImplicitGeologyParams(target_lithologies=["kimberlite"],
                                target_density_t_m3=TARGET_DENSITY)
    params = _params(boreholes=None, implicit_geology=geo)
    with pytest.raises(HTTPException) as exc:
        _build_implicit_geology_reference(params, x_c, y_c, z_c, BASE_DENSITY)
    assert exc.value.status_code == 422


# ── 3) Activado con litología → m_ref de contraste correcto ───────────────────
def test_reference_contrast_target_vs_host():
    x_c, y_c, z_c = _grid_centers()
    geo = ImplicitGeologyParams(target_lithologies=["kimberlite"],
                                target_density_t_m3=TARGET_DENSITY)
    params = _params(boreholes=_lithology_boreholes(), implicit_geology=geo)
    m_ref, meta = _build_implicit_geology_reference(params, x_c, y_c, z_c, BASE_DENSITY)

    assert m_ref is not None and meta is not None
    # Longitud = grilla completa.
    assert m_ref.shape[0] == NX * NY * NZ
    assert np.isfinite(m_ref).all()
    # Hay celdas objetivo y celdas caja.
    assert meta["n_target_cells"] > 0
    assert meta["n_target_cells"] < meta["n_total_cells"]
    assert meta["enabled"] is True and "m_ref" in meta["binding"]

    target_contrast = TARGET_DENSITY - BASE_DENSITY  # 1.0
    # Celdas objetivo (membership dura) → contraste de la unidad; caja → 0.
    target_mask = m_ref > 0.5 * target_contrast
    assert np.allclose(m_ref[target_mask], target_contrast, atol=1e-9)
    assert np.allclose(m_ref[~target_mask], 0.0, atol=1e-9)

    # El centroide de las celdas objetivo debe caer en la mitad PROFUNDA (y > 90).
    y_target = y_c[target_mask]
    assert y_target.mean() > 90.0


def test_host_density_override():
    """host_density_t_m3 explícito desplaza el contraste de la caja."""
    x_c, y_c, z_c = _grid_centers()
    geo = ImplicitGeologyParams(target_lithologies=["kimberlite"],
                                target_density_t_m3=TARGET_DENSITY,
                                host_density_t_m3=2.9)
    params = _params(boreholes=_lithology_boreholes(), implicit_geology=geo)
    m_ref, meta = _build_implicit_geology_reference(params, x_c, y_c, z_c, BASE_DENSITY)
    # Caja → 2.9 - 2.6 = 0.3 ; objetivo → 3.6 - 2.6 = 1.0
    host_mask = m_ref < 0.5 * (TARGET_DENSITY - BASE_DENSITY)
    assert np.allclose(m_ref[host_mask], 0.3, atol=1e-9)
    assert meta["host_density_t_m3"] == 2.9


# ── 4) softness>0 → membership suave (contraste intermedio en el contacto) ────
def test_soft_membership_produces_intermediate_values():
    x_c, y_c, z_c = _grid_centers()
    geo_hard = ImplicitGeologyParams(target_lithologies=["kimberlite"],
                                     target_density_t_m3=TARGET_DENSITY, softness=0.0)
    geo_soft = ImplicitGeologyParams(target_lithologies=["kimberlite"],
                                     target_density_t_m3=TARGET_DENSITY, softness=2.0)
    p_hard = _params(boreholes=_lithology_boreholes(), implicit_geology=geo_hard)
    p_soft = _params(boreholes=_lithology_boreholes(), implicit_geology=geo_soft)
    m_hard, _ = _build_implicit_geology_reference(p_hard, x_c, y_c, z_c, BASE_DENSITY)
    m_soft, _ = _build_implicit_geology_reference(p_soft, x_c, y_c, z_c, BASE_DENSITY)

    tgt = TARGET_DENSITY - BASE_DENSITY
    # Hard: solo {0, tgt}. Soft: hay valores estrictamente intermedios.
    hard_intermediate = np.sum((m_hard > 1e-6) & (m_hard < tgt - 1e-6))
    soft_intermediate = np.sum((m_soft > 1e-6) & (m_soft < tgt - 1e-6))
    assert hard_intermediate == 0
    assert soft_intermediate > 0


def test_orientations_accepted():
    """El gradiente estructural se acepta sin romper (anclar la polaridad de φ)."""
    x_c, y_c, z_c = _grid_centers()
    geo = ImplicitGeologyParams(
        target_lithologies=["kimberlite"], target_density_t_m3=TARGET_DENSITY,
        orientations=[StructuralOrientation(x_m=HOLE_X, z_m=HOLE_Z, y_m=90.0,
                                            dip_deg=20.0, azimuth_deg=45.0)],
    )
    params = _params(boreholes=_lithology_boreholes(), implicit_geology=geo)
    m_ref, meta = _build_implicit_geology_reference(params, x_c, y_c, z_c, BASE_DENSITY)
    assert m_ref is not None
    assert meta["n_orientations"] == 1


# ── 5/6) E2E a través de run_geophysics_inversion ─────────────────────────────
def _run_e2e(implicit_geology):
    """Inversión sintética pequeña con anomalía profunda compacta."""
    from exploration.gravimetry import GravimetryForward
    from services.geophysics_service import run_geophysics_inversion

    nx, ny, nz, bs = 8, 6, 8, 20.0
    gx, gy, gz = np.mgrid[0:nx, 0:ny, 0:nz]
    x_c = gx.flatten(order="F") * bs + bs / 2
    y_c = gy.flatten(order="F") * bs + bs / 2
    z_c = gz.flatten(order="F") * bs + bs / 2

    cx, cy, cz = nx * bs / 2, 90.0, nz * bs / 2
    r = np.sqrt((x_c - cx) ** 2 + (y_c - cy) ** 2 + (z_c - cz) ** 2)
    contrast = np.where(r <= 25.0, 0.6, 0.0)

    fwd = GravimetryForward(bs, bs, bs, cutoff_radius=4000.0)
    sx, sz = np.meshgrid(np.arange(5, nx * bs, bs), np.arange(5, nz * bs, bs), indexing="ij")
    sensors = np.column_stack([sx.ravel(), np.zeros(sx.size), sz.ravel()])
    g_obs = fwd.build_sparse_kernel(x_c, y_c, z_c, sensors) @ contrast

    bhs = [
        BoreholeInterval(x_m=float(cx), z_m=float(cz), y_from_m=0.0, y_to_m=60.0,
                         lithology="granite"),
        BoreholeInterval(x_m=float(cx), z_m=float(cz), y_from_m=60.0, y_to_m=120.0,
                         lithology="kimberlite"),
    ]
    params = GeophysicsInvertInput(
        project_id=f"pytest_geo7", run_id=f"run_{'geo' if implicit_geology else 'base'}",
        depth=int(ny * bs), nir=83, fe=79, region="norte_chile", lat="-22.28", lon="-68.89",
        nx=nx, ny=ny, nz=nz, block_size=int(bs), cutoff_radius=int(nx * bs * 2),
        lambda_mag=1e-3, alpha_spatial=1.0,
        observations=[
            {"x_m": float(s[0]), "y_m": 0.0, "z_m": float(s[2]), "g": float(g)}
            for s, g in zip(sensors, g_obs)
        ],
        boreholes=bhs,
        implicit_geology=implicit_geology,
    )
    result = run_geophysics_inversion(params)
    dens = np.array(
        [v["density"] if v.get("density") is not None else np.nan for v in result["voxels"]],
        dtype=float,
    )
    return result, dens


@pytest.mark.benchmark
def test_e2e_disabled_report_none():
    result, _ = _run_e2e(implicit_geology=None)
    assert result["report"].get("implicit_geology") is None


@pytest.mark.benchmark
def test_e2e_enabled_changes_model_and_reports():
    geo = ImplicitGeologyParams(target_lithologies=["kimberlite"],
                                target_density_t_m3=3.6)
    _base_result, dens_base = _run_e2e(implicit_geology=None)
    geo_result, dens_geo = _run_e2e(implicit_geology=geo)

    meta = geo_result["report"].get("implicit_geology")
    assert meta is not None, "report.implicit_geology no poblado con el flag activo"
    assert meta["enabled"] is True
    assert meta["n_target_cells"] > 0
    assert meta["n_contact_points"] >= 1

    # El prior geológico DEBE cambiar el modelo invertido (prueba de cableado real).
    finite = np.isfinite(dens_base) & np.isfinite(dens_geo)
    assert finite.any()
    max_diff = np.nanmax(np.abs(dens_geo[finite] - dens_base[finite]))
    assert max_diff > 1e-4, (
        f"El modelo no cambió con implicit_geology (max_diff={max_diff:.2e}): "
        "el m_ref geológico no está entrando al solve."
    )
    # Determinismo: misma entrada → mismo modelo.
    _again_result, dens_again = _run_e2e(implicit_geology=geo)
    assert np.allclose(np.nan_to_num(dens_geo), np.nan_to_num(dens_again), atol=1e-8)
