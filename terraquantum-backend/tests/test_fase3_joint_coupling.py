"""
FASE 3.1 — Acoplamiento conjunto: PGI dinámico 2D (ρ-χ) vs cross-gradient.

Verifica el nuevo `joint_coupling_mode` del orquestador de inversión conjunta:
  - 'cross_gradient' (default) es BYTE-IDÉNTICO al comportamiento histórico.
  - 'pgi_dynamic' y 'pgi+cross' corren sin explotar, producen modelos finitos y
    reportan el bloque de acoplamiento (modo, medias 2D del GMM, mean_shift).
  - el GMM 2D bootstrap + refit NIW mueve las clases sin colapsar.

El PGI conjunto acopla por PETROFÍSICA (centroide 2D de la clase de cada celda),
no solo por estructura. NO se afirma aquí ganancia E2E sobre un benchmark real
(DO-27/Raglan) — eso queda como evidencia pendiente (mismo matiz que Fase 2).
"""
import numpy as np
import pytest

from schemas.geophysics_schema import GeophysicsInvertInput
from services.joint_inversion import run_joint_inversion
from exploration.gravimetry import GravimetryForward
from exploration.magnetometry import MagnetometryForward


def _build_joint_params(project_id, run_id, coupling_mode="cross_gradient",
                        offset=False, **overrides):
    """Escenario sintético con señal NO nula en ambas físicas. joint_max_iter bajo.

    offset=False: un cuerpo co-localizado (alta ρ y alta χ, tipo magnetita) → estructura
        ya alineada (E_norm bajo, el bucle puede parar temprano).
    offset=True: cuerpos DESFASADOS (ρ y χ en lugares distintos) → disimilitud estructural
        alta → el bucle itera y el acoplamiento (cross/PGI) se activa en k≥2.
    """
    nx, ny, nz, dx = 8, 6, 8, 50.0
    nC = nx * ny * nz
    ix, iy, iz = np.mgrid[0:nx, 0:ny, 0:nz]
    ix = ix.flatten(order="F"); iy = iy.flatten(order="F"); iz = iz.flatten(order="F")
    x_c = ix * dx + dx / 2.0
    y_c = iy * dx + dx / 2.0
    z_c = iz * dx + dx / 2.0

    cy = ny * dx * 0.5
    if offset:
        # ρ a la izquierda, χ a la derecha → gradientes desfasados (E_norm alto).
        d2_r = (x_c - nx * dx * 0.30) ** 2 + (y_c - cy) ** 2 + (z_c - nz * dx * 0.50) ** 2
        d2_c = (x_c - nx * dx * 0.70) ** 2 + (y_c - cy) ** 2 + (z_c - nz * dx * 0.50) ** 2
        rho_true = 2.6 + 0.8 * np.exp(-d2_r / (2.0 * (1.1 * dx) ** 2))
        susc_true = 0.6 * np.exp(-d2_c / (2.0 * (1.1 * dx) ** 2))
    else:
        # Cuerpo gaussiano co-localizado: contraste de densidad Y susceptibilidad.
        cx, cz = nx * dx * 0.5, nz * dx * 0.5
        d2 = (x_c - cx) ** 2 + (y_c - cy) ** 2 + (z_c - cz) ** 2
        blob = np.exp(-d2 / (2.0 * (1.3 * dx) ** 2))
        rho_true = 2.6 + 0.8 * blob
        susc_true = 0.6 * blob

    sx = np.linspace(0.5 * dx, (nx - 0.5) * dx, 6)
    sz = np.linspace(0.5 * dx, (nz - 0.5) * dx, 6)
    SX, SZ = np.meshgrid(sx, sz)
    sensors = np.column_stack([SX.ravel(), np.full(SX.size, -dx), SZ.ravel()])
    cutoff = (nx + nz) * dx

    grav_fwd = GravimetryForward(dx, dx, dx, cutoff_radius=cutoff)
    mag_fwd = MagnetometryForward(dx, dx, dx, cutoff_radius=cutoff,
                                  inclination_deg=-30.0, declination_deg=2.0,
                                  field_intensity_nt=23500.0)
    Kg = grav_fwd.build_sparse_kernel(x_c, y_c, z_c, sensors)
    Km = mag_fwd.build_sparse_kernel(x_c, y_c, z_c, sensors)
    g_obs = Kg @ (rho_true - 2.6)
    tmi_obs = Km @ susc_true

    observations = [
        {"x_m": float(sensors[i, 0]), "y_m": float(sensors[i, 1]),
         "z_m": float(sensors[i, 2]), "g": float(g_obs[i])}
        for i in range(sensors.shape[0])
    ]

    kw = dict(
        project_id=project_id, run_id=run_id,
        depth=int(ny * dx // 2), nir=50, fe=50, region="norte_chile",
        lat="-23.5", lon="-69.0",
        nx=nx, ny=ny, nz=nz, block_size=int(dx),
        cutoff_radius=float(cutoff), lambda_mag=1e-3, alpha_spatial=1.0,
        observations=observations,
        magnetic_nt=[float(v) for v in tmi_obs],
        inclination_deg=-30.0, declination_deg=2.0, field_intensity_nt=23500.0,
        susc_min=0.0, susc_max=1.0,
        density_min=2.6, density_max=4.2,
        joint_max_iter=3, cross_lambda_beta=0.05,
        joint_coupling_mode=coupling_mode,
    )
    kw.update(overrides)
    return GeophysicsInvertInput(**kw)


def _density_field(result):
    """Reconstruye el vector denso de densidad desde los voxels devueltos (orden por índice)."""
    vox = result["voxels"]
    return np.array([(v["ix"], v["iy"], v["iz"], v["density_t_m3"], v["susceptibility_si"]) for v in vox])


@pytest.mark.benchmark
def test_default_is_cross_gradient_byte_identical(test_project_id, test_run_id):
    """El default (sin joint_coupling_mode) == 'cross_gradient' explícito, byte-idéntico."""
    p_default = _build_joint_params(test_project_id, test_run_id)
    assert p_default.joint_coupling_mode == "cross_gradient"
    r_default = run_joint_inversion(p_default)

    p_explicit = _build_joint_params(test_project_id, test_run_id, coupling_mode="cross_gradient")
    r_explicit = run_joint_inversion(p_explicit)

    a, b = _density_field(r_default), _density_field(r_explicit)
    assert a.shape == b.shape
    assert np.array_equal(a, b), "cross_gradient default debe ser byte-idéntico al explícito."
    assert r_default["misfit_error_percent"] == r_explicit["misfit_error_percent"]
    # El path histórico no debe declarar PGI.
    assert r_default["report"]["coupling"]["use_pgi"] is False


@pytest.mark.benchmark
def test_pgi_dynamic_runs_and_reports(test_project_id, test_run_id):
    """'pgi_dynamic' corre, produce modelos finitos y reporta el bloque de acoplamiento."""
    p = _build_joint_params(test_project_id, test_run_id, coupling_mode="pgi_dynamic",
                            offset=True, joint_pgi_alpha=0.2, joint_pgi_n_classes=3)
    r = run_joint_inversion(p)
    coupling = r["report"]["coupling"]
    assert coupling["mode"] == "pgi_dynamic"
    assert coupling["use_pgi"] is True
    assert coupling["use_cross_gradient"] is False
    assert coupling["pgi_disabled_reason"] is None, "El GMM 2D debió ajustarse (sklearn disponible)."
    means = np.asarray(coupling["pgi_gmm_means_rho_chi"], dtype=float)
    assert means.shape == (3, 2)
    assert np.isfinite(means).all()
    # Modelos finitos y dentro de bounds.
    for v in r["voxels"]:
        assert np.isfinite(v["density_t_m3"]) and np.isfinite(v["susceptibility_si"])
        assert 2.6 - 1e-6 <= v["density_t_m3"] <= 4.2 + 1e-6
        assert -1e-9 <= v["susceptibility_si"] <= 1.0 + 1e-6
    # El refit dinámico debe haberse activado (mean_shift presente en alguna iteración k>=2).
    hist = r["report"]["convergence_history"]
    assert any(h.get("pgi_active") for h in hist[1:]), "PGI debió activarse en k>=2."


@pytest.mark.benchmark
def test_pgi_plus_cross_combines_both(test_project_id, test_run_id):
    """'pgi+cross' activa AMBOS acoplamientos y converge sin explotar."""
    p = _build_joint_params(test_project_id, test_run_id, coupling_mode="pgi+cross",
                            offset=True, joint_pgi_alpha=0.1)
    r = run_joint_inversion(p)
    coupling = r["report"]["coupling"]
    assert coupling["use_pgi"] is True
    assert coupling["use_cross_gradient"] is True
    assert np.isfinite(r["report"]["final"]["E_norm"])
    assert len(r["voxels"]) > 0


@pytest.mark.benchmark
def test_pgi_does_not_blow_up_misfit(test_project_id, test_run_id):
    """El acoplamiento PGI no debe degradar catastróficamente el misfit vs cross-gradient."""
    r_cross = run_joint_inversion(_build_joint_params(test_project_id, test_run_id))
    r_pgi = run_joint_inversion(
        _build_joint_params(test_project_id, test_run_id, coupling_mode="pgi_dynamic",
                            joint_pgi_alpha=0.1)
    )
    m_cross = r_cross["misfit_error_percent"]
    m_pgi = r_pgi["misfit_error_percent"]
    assert np.isfinite(m_pgi)
    # Tolerancia amplia: el PGI smallness no debe disparar el misfit a >3x el cross-gradient.
    assert m_pgi <= max(3.0 * m_cross, 50.0), (
        f"PGI degradó el misfit demasiado: cross={m_cross:.2f}% vs pgi={m_pgi:.2f}%"
    )


@pytest.mark.benchmark
def test_gramian_runs_and_differs_from_cross(test_project_id, test_run_id):
    """'gramian' (Zhdanov, gradiente crudo) corre, reporta use_gramian y NO es idéntico
    al cross-gradient (dirección unitaria) — distinta normalización → distinto resultado."""
    p_cross = _build_joint_params(test_project_id, test_run_id, offset=True)
    r_cross = run_joint_inversion(p_cross)

    p_gram = _build_joint_params(test_project_id, test_run_id, coupling_mode="gramian", offset=True)
    r_gram = run_joint_inversion(p_gram)

    cpl = r_gram["report"]["coupling"]
    assert cpl["mode"] == "gramian"
    assert cpl["use_gramian"] is True
    assert cpl["use_cross_gradient"] is False
    assert cpl["structural_kind"] == "gramian"
    assert cpl["use_pgi"] is False
    # El Gramian (gradiente crudo) debe producir un modelo DISTINTO al cross-gradient unitario.
    a, b = _density_field(r_gram), _density_field(r_cross)
    assert not (a.shape == b.shape and np.array_equal(a, b)), (
        "gramian debería diferir del cross-gradient (normalización distinta)."
    )
    # Finito y acotado.
    assert np.isfinite(r_gram["report"]["final"]["E_norm"])
    assert np.isfinite(r_gram["misfit_error_percent"])
    for v in r_gram["voxels"]:
        assert np.isfinite(v["density_t_m3"]) and np.isfinite(v["susceptibility_si"])


@pytest.mark.unit
def test_fixed_gradient_dirs_raw_vs_unit():
    """El helper devuelve gradiente CRUDO para gramian y UNITARIO para cross-gradient."""
    from services.joint_inversion import _fixed_gradient_dirs
    from exploration.geophysics_math import build_gradient_operators
    nx = ny = nz = 5
    Dx, Dy, Dz = build_gradient_operators(nx, ny, nz, 1.0, 1.0, 1.0)
    # Rampa lineal en X con pendiente grande → gradiente crudo ~grande; unitario ~1.
    ix = np.mgrid[0:nx, 0:ny, 0:nz][0].flatten(order="F").astype(float)
    m = 10.0 * ix
    gx_raw, _, _ = _fixed_gradient_dirs(m, Dx, Dy, Dz, "gramian")
    gx_unit, _, _ = _fixed_gradient_dirs(m, Dx, Dy, Dz, "cross_gradient")
    interior = np.abs(gx_raw) > 1e-9
    assert np.nanmax(np.abs(gx_raw)) > 5.0, "gradiente crudo debe reflejar la pendiente real"
    assert np.allclose(np.abs(gx_unit[interior]), 1.0, atol=1e-6), "dirección unitaria ~1"


@pytest.mark.benchmark
def test_joint_padding_runs_and_reduces_to_core(test_project_id, test_run_id):
    """Fase 3.3: joint_padding corre sobre malla extendida y reduce al core.

    El bloque 3D de salida debe contener SOLO celdas core (nx*ny*nz), el report debe
    declarar padding.active=True con n_total>n_core, y los índices de voxel deben caer
    dentro del rango core.
    """
    nx, ny, nz = 8, 6, 8
    p = _build_joint_params(test_project_id, test_run_id, offset=False,
                            joint_padding=True, joint_n_pad=3, joint_pad_factor=1.3)
    r = run_joint_inversion(p)
    mesh = r["report"]["mesh"]
    pad = mesh["padding"]
    assert pad["active"] is True
    assert pad["n_total_cells"] > pad["n_core_cells"]
    assert pad["n_core_cells"] == nx * ny * nz
    assert mesh["n_active"] == nx * ny * nz
    # Todos los voxels de salida deben estar en el rango core.
    for v in r["voxels"]:
        assert 0 <= v["ix"] < nx and 0 <= v["iy"] < ny and 0 <= v["iz"] < nz
        assert np.isfinite(v["density_t_m3"]) and np.isfinite(v["susceptibility_si"])
    assert np.isfinite(r["misfit_error_percent"])
    assert len(r["voxels"]) > 0


@pytest.mark.benchmark
def test_joint_padding_with_pgi_coupling(test_project_id, test_run_id):
    """Fase 3.3 + 3.1: padding y PGI dinámico co-existen sin explotar."""
    p = _build_joint_params(test_project_id, test_run_id, offset=True,
                            coupling_mode="pgi+cross", joint_pgi_alpha=0.1,
                            joint_padding=True, joint_n_pad=3)
    r = run_joint_inversion(p)
    assert r["report"]["mesh"]["padding"]["active"] is True
    assert r["report"]["coupling"]["use_pgi"] is True
    assert r["report"]["coupling"]["pgi_disabled_reason"] is None
    assert np.isfinite(r["report"]["final"]["E_norm"])
    assert len(r["voxels"]) > 0


@pytest.mark.unit
def test_invalid_coupling_mode_rejected(test_project_id, test_run_id):
    """Un joint_coupling_mode inválido es rechazado por el schema (pydantic)."""
    from pydantic import ValidationError
    with pytest.raises(ValidationError):
        _build_joint_params(test_project_id, test_run_id, coupling_mode="bogus_mode")


@pytest.mark.unit
def test_joint_gmm_2d_helpers_recover_clusters():
    """El bootstrap + responsabilidades 2D recuperan dos clústeres ρ-χ separados."""
    from services.joint_inversion import _fit_joint_gmm_2d, _joint_pgi_class_means
    rng = np.random.default_rng(7)
    # Clúster A: roca caja (ρ≈2.6, χ≈0). Clúster B: magnetita (ρ≈3.4, χ≈0.6).
    n = 200
    rhoA = 2.6 + 0.03 * rng.standard_normal(n); chiA = 0.01 + 0.005 * rng.standard_normal(n)
    rhoB = 3.4 + 0.05 * rng.standard_normal(n); chiB = 0.60 + 0.03 * rng.standard_normal(n)
    rho = np.concatenate([rhoA, rhoB]); chi = np.concatenate([chiA, chiB])
    means, covs, weights = _fit_joint_gmm_2d(rho, chi, n_classes=2)
    assert means.shape == (2, 2) and covs.shape == (2, 2, 2)
    # Las medias deben capturar los dos centroides (ρ separados ~0.8).
    rho_means = np.sort(means[:, 0])
    assert rho_means[1] - rho_means[0] > 0.4
    # La referencia por celda asigna a su clúster: una celda magnetita → ρ_ref alto.
    rho_ref, chi_ref = _joint_pgi_class_means(
        np.array([3.4]), np.array([0.6]), means, covs, weights
    )
    assert rho_ref[0] > 3.0 and chi_ref[0] > 0.4
