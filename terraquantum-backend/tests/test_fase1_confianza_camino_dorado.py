"""
FASE 1 (auditoría 06 §10) — Los bugs de confianza del camino dorado · backend.
==============================================================================

Cubre los dos hallazgos de backend de la fase. Ambos comparten consecuencia: el
producto entregaba algo válido en apariencia que no correspondía a la realidad de
la corrida — la categoría que docs/05 Parte C define como enemigo #1 ("el número
corrupto con cara de bueno"), aquí aplicada a la PROCEDENCIA del resultado.

  • H-37 — el modo `amplitude` fantasma. El esquema lo aceptaba, la UI lo ofrecía,
    el motor NUNCA lo despachaba (sólo hay rama para `total_field`) y el reporte
    escribía `inversion_mode: "amplitude"`. Ahora se RECHAZA en voz alta con un
    error del catálogo ES antes de gastar un solo ciclo de solver.

  • H-27 — la caída a topografía PLANA. La interpolación de superficie puede fallar
    y la corrida continúa con terreno horizontal: cambia la máscara de aire y la
    profundidad verdadera de cada celda. Sólo quedaba en el log estructurado; ahora
    viaja por `warnings[]` (canal que el frontend ya renderiza) y como bandera
    estructurada `topography_degraded`.

No se tunea ningún umbral físico: se afirma el contrato de honestidad.
"""
from __future__ import annotations

import os
import sys

import numpy as np
import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.errors import CATALOG, TerraquantumError
from schemas.geophysics_schema import (
    GeophysicsInvertInput,
    GravityObservation,
    MagneticRemanenceParams,
)
from services.geophysics_service import (
    TOPOGRAPHY_FLAT_FALLBACK_WARNING,
    reject_unavailable_inversion_modes,
    run_geophysics_inversion,
    run_magnetic_inversion,
    topography_run_warnings,
)

INC, DEC, B0 = -30.0, 2.0, 23500.0
NX, NY, NZ, BLOCK = 6, 8, 6, 20.0


# ─────────────────────────────────────────────────────────────────────────────
# Builders (malla mínima: estos tests afirman contrato, no física)
# ─────────────────────────────────────────────────────────────────────────────

def _magnetic_input(*, remanence=None, with_elevations=False) -> GeophysicsInvertInput:
    """Input magnético-aislado (g=0) con TMI sintetizada sobre la grilla del servicio."""
    from exploration.magnetometry import MagnetometryForward
    from services.geophysics_service import build_voxel_grid

    obs = [
        GravityObservation(x_m=10 + i * 20, y_m=0.0, z_m=10 + j * 20, g=0.0)
        for i in range(6)
        for j in range(6)
    ]
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
    _ix, _iy, _iz, x_c, y_c, z_c = build_voxel_grid(base)
    fwd = MagnetometryForward(
        BLOCK, BLOCK, BLOCK, cutoff_radius=200.0,
        inclination_deg=INC, declination_deg=DEC, field_intensity_nt=B0,
    )
    kappa = np.zeros(len(x_c))
    kappa[((x_c - 60) ** 2 + (y_c - 50) ** 2 + (z_c - 60) ** 2) < 25 ** 2] = 0.2
    d = fwd.build_sparse_kernel(x_c, y_c, z_c, sensors) @ kappa

    update = {"magnetic_nt": d.tolist()}
    if remanence is not None:
        update["remanence"] = remanence
    if with_elevations:
        update["sensor_elevations_masl"] = [1000.0 + 0.05 * (o.x_m + o.z_m) for o in obs]
    return base.model_copy(update=update)


def _gravity_input(*, with_elevations=True, run_id="fase1_topo") -> GeophysicsInvertInput:
    """Input gravimétrico pequeño con un cuerpo compacto sintético."""
    from exploration.gravimetry import GravimetryForward

    gx, gy, gz = np.mgrid[0:NX, 0:NY, 0:NZ]
    x_c = gx.flatten(order="F") * BLOCK + BLOCK / 2
    y_c = gy.flatten(order="F") * BLOCK + BLOCK / 2
    z_c = gz.flatten(order="F") * BLOCK + BLOCK / 2
    r = np.sqrt((x_c - NX * BLOCK / 2) ** 2 + (y_c - 70.0) ** 2 + (z_c - NZ * BLOCK / 2) ** 2)
    contrast = np.where(r <= 25.0, 0.8, 0.0)

    fwd = GravimetryForward(BLOCK, BLOCK, BLOCK, cutoff_radius=4000.0)
    sx, sz = np.meshgrid(
        np.arange(5, NX * BLOCK, BLOCK), np.arange(5, NZ * BLOCK, BLOCK), indexing="ij",
    )
    sensors = np.column_stack([sx.ravel(), np.zeros(sx.size), sz.ravel()])
    g_obs = fwd.build_sparse_kernel(x_c, y_c, z_c, sensors) @ contrast

    params = GeophysicsInvertInput(
        project_id="pytest_fase1", run_id=run_id,
        depth=int(NY * BLOCK), nir=83, fe=79, region="norte_chile", lat="-22.28", lon="-68.89",
        nx=NX, ny=NY, nz=NZ, block_size=int(BLOCK), cutoff_radius=int(NX * BLOCK * 2),
        lambda_mag=1e-3, alpha_spatial=1.0,
        observations=[
            {"x_m": float(s[0]), "y_m": 0.0, "z_m": float(s[2]), "g": float(g)}
            for s, g in zip(sensors, g_obs)
        ],
    )
    if with_elevations:
        params = params.model_copy(update={
            "sensor_elevations_masl": [1000.0 + 0.05 * float(s[0] + s[2]) for s in sensors],
        })
    return params


@pytest.fixture
def broken_surface_interpolation(monkeypatch):
    """Fuerza el fallback: la interpolación de superficie levanta excepción."""
    import core.geo_utils as geo_utils

    def _boom(*_args, **_kwargs):
        raise RuntimeError("fallo sintético de interpolación de superficie")

    monkeypatch.setattr(geo_utils, "interpolate_surface_depths", _boom)


# ═════════════════════════════════════════════════════════════════════════════
# H-37 — El modo `amplitude` fantasma
# ═════════════════════════════════════════════════════════════════════════════

def test_catalog_has_unavailable_mode_entry():
    """El rechazo usa el catálogo ES, no un mensaje crudo inventado en el sitio."""
    spec = CATALOG["INVERSION_MODE_UNAVAILABLE"]
    assert spec.severity == "error"
    assert len(spec.user_message) > 100
    assert spec.suggested_action


def test_amplitude_is_rejected_by_the_orchestrator():
    """El punto de entrada único rechaza `amplitude` ANTES de rutear a ningún motor."""
    params = _magnetic_input(
        remanence=MagneticRemanenceParams(enabled=True, q_ratio=1.5, inversion_mode="amplitude"),
    )
    with pytest.raises(TerraquantumError) as exc:
        run_geophysics_inversion(params)
    assert exc.value.code == "INVERSION_MODE_UNAVAILABLE"
    assert "amplitude" in exc.value.user_message
    assert exc.value.technical_details["requested_inversion_mode"] == "amplitude"
    # El canal async (run_queue_service) serializa por aquí: debe traer código y acción.
    details = exc.value.to_error_details(source="test", stage="solving")
    assert details["code"] == "INVERSION_MODE_UNAVAILABLE"
    assert details["details"]["suggested_action"]


def test_amplitude_is_rejected_by_the_magnetic_engine_directly():
    """Quien llame al motor magnético sin pasar por el orquestador también se topa."""
    params = _magnetic_input(
        remanence=MagneticRemanenceParams(enabled=True, q_ratio=1.5, inversion_mode="amplitude"),
    )
    with pytest.raises(TerraquantumError) as exc:
        run_magnetic_inversion(params)
    assert exc.value.code == "INVERSION_MODE_UNAVAILABLE"


def test_amplitude_is_rejected_even_with_remanence_disabled():
    """`enabled=False` no vuelve honesto al modo: si se declara, se rechaza."""
    params = _magnetic_input(
        remanence=MagneticRemanenceParams(enabled=False, inversion_mode="amplitude"),
    )
    with pytest.raises(TerraquantumError):
        reject_unavailable_inversion_modes(params)


@pytest.mark.parametrize("mode", ["induced_only", "total_field"])
def test_dispatched_modes_pass_the_guard(mode):
    """Los modos que el motor SÍ ejecuta no son rechazados (el guard no es un muro)."""
    params = _magnetic_input(
        remanence=MagneticRemanenceParams(enabled=True, q_ratio=1.0, inversion_mode=mode),
    )
    reject_unavailable_inversion_modes(params)  # no debe levantar


def test_no_remanence_block_passes_the_guard():
    """El caso mayoritario (sin bloque de remanencia) no toca el guard."""
    reject_unavailable_inversion_modes(_gravity_input(with_elevations=False))


def test_induced_run_reports_the_mode_it_actually_executed():
    """No-regresión de procedencia: lo que el reporte declara es lo que se corrió."""
    res = run_magnetic_inversion(_magnetic_input())
    assert res["report"]["remanence"] is None
    assert "inducida" in res["report"]["engine"]


# ═════════════════════════════════════════════════════════════════════════════
# H-27 — La caída a topografía PLANA llega al usuario
# ═════════════════════════════════════════════════════════════════════════════

@pytest.mark.parametrize("state", ["flat", "from_sensor_elevations_masl[linear]", ""])
def test_no_warning_when_topography_is_not_degraded(state):
    """Sin degradación no hay ruido: el aviso es señal, no decoración."""
    assert topography_run_warnings(state) == []


def test_warning_text_is_actionable_spanish():
    warns = topography_run_warnings("flat_fallback")
    assert warns == [TOPOGRAPHY_FLAT_FALLBACK_WARNING]
    assert "PLANA" in warns[0] and "elevación" in warns[0]
    assert len(warns[0]) > 100


def test_magnetic_run_declares_flat_fallback_in_warnings(broken_surface_interpolation):
    """Motor magnético: la degradación queda declarada en el reporte, no sólo en el log."""
    res = run_magnetic_inversion(_magnetic_input(with_elevations=True))
    report = res["report"]
    assert report["topography_used"] == "flat_fallback"
    assert report["topography_degraded"] is True
    assert TOPOGRAPHY_FLAT_FALLBACK_WARNING in report["warnings"]
    # El campo histórico de la malla se conserva (no se rompe ningún consumidor).
    assert report["mesh"]["topography"] == "flat_fallback"


def test_magnetic_healthy_topography_emits_no_warning():
    res = run_magnetic_inversion(_magnetic_input(with_elevations=True))
    report = res["report"]
    assert report["topography_used"].startswith("from_sensor_elevations_masl")
    assert report["topography_degraded"] is False
    assert report["warnings"] == []


def test_gravity_run_declares_flat_fallback_in_warnings(broken_surface_interpolation):
    """Motor gravimétrico: mismo contrato, y también en technicalSummary.warnings."""
    res = run_geophysics_inversion(_gravity_input(run_id="fase1_topo_degraded"))
    report = res["report"]
    assert report["topography_used"] == "flat_fallback"
    assert report["topography_degraded"] is True
    assert TOPOGRAPHY_FLAT_FALLBACK_WARNING in report["warnings"]
    assert TOPOGRAPHY_FLAT_FALLBACK_WARNING in report["technicalSummary"]["warnings"]


def test_gravity_healthy_topography_emits_no_topography_warning():
    res = run_geophysics_inversion(_gravity_input(run_id="fase1_topo_ok"))
    report = res["report"]
    assert report["topography_used"].startswith("from_sensor_elevations_masl")
    assert report["topography_degraded"] is False
    assert TOPOGRAPHY_FLAT_FALLBACK_WARNING not in report["warnings"]
