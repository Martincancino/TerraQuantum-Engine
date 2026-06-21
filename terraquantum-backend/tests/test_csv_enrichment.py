"""Tests del pipeline de ENRIQUECIMIENTO de paquetes CSV (Preparación).

Cubren cada paso por separado (DEM/correcciones/IGRF/coords/σ) con stubs livianos
(sin red ni FastAPI), el caso NO-derivable (queda null + bandera) y el caso SIN
contexto (aviso accionable). GUARDRAIL: se verifica que cada columna nueva proviene
de física/matemática real y que lo no-derivable no fabrica números.
"""
import asyncio
import os
import sys
from types import SimpleNamespace

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from services.csv_enrichment_service import (
    enrich_package,
    sample_dem_elevations,
    derive_sigmas_mgal,
    resolve_igrf,
    reconstruct_latlon_from_utm,
    valid_latlon_list,
    STATUS_DERIVED,
    STATUS_ALREADY_PRESENT,
    STATUS_NEEDS_CONTEXT,
    STATUS_NOT_DERIVABLE,
    STATUS_SKIPPED,
)


# ── Stubs ────────────────────────────────────────────────────────────────────
def _obs(n, g_mgal=5.0):
    return [
        SimpleNamespace(x_m=float(i * 100), y_m=0.0, z_m=float((i % 3) * 100), g=g_mgal * 1e-5)
        for i in range(n)
    ]


def _quality(score=80.0, interp="GOOD"):
    return SimpleNamespace(
        version="data_quality_v0_1", score=score, interpretation=interp,
        completeness=90.0, spatial_distribution=70.0, noise_level=60.0,
    )


def _primary(
    n=9, *, gravity_type="bouguer_anomaly", raw_latlon=None,
    station_elevations=None, coordinate_transform=None, quality=True,
):
    csv_analysis = SimpleNamespace(data_quality=_quality()) if quality else None
    return SimpleNamespace(
        observations=_obs(n),
        raw_latlon_elev=raw_latlon,
        station_elevations=station_elevations,
        station_uncertainties=None,
        magnetic_values=None,
        coordinate_transform=coordinate_transform,
        import_metadata=SimpleNamespace(gravity_type=gravity_type),
        csv_analysis=csv_analysis,
        warnings=[],
    )


def _step(result, key):
    return next(s for s in result.steps if s.key == key)


# ── 1. Muestreo bilineal de DEM (pura) ───────────────────────────────────────
def test_sample_dem_bilinear_exact_on_linear_field():
    """Sobre un campo lineal, la interpolación bilineal es EXACTA."""
    # DEM 3x3, lat descendente (norte→sur), lon ascendente. elev = 100*lon + 10*lat.
    lon_1d = np.array([0.0, 1.0, 2.0])
    lat_1d = np.array([2.0, 1.0, 0.0])  # descendente
    elev = np.array([[100 * lo + 10 * la for lo in lon_1d] for la in lat_1d])
    lats = np.array([1.5, 0.5])
    lons = np.array([0.5, 1.5])
    out = sample_dem_elevations(lats, lons, lat_1d, lon_1d, elev)
    expected = 100 * lons + 10 * lats
    assert np.allclose(out, expected, atol=1e-9)


def test_sample_dem_clamps_outside_bbox():
    lon_1d = np.array([0.0, 1.0])
    lat_1d = np.array([1.0, 0.0])
    elev = np.array([[5.0, 6.0], [7.0, 8.0]])
    out = sample_dem_elevations(np.array([5.0]), np.array([5.0]), lat_1d, lon_1d, elev)
    assert 5.0 <= out[0] <= 8.0  # recortado al borde, no extrapola a infinito


# ── 2. σ por estación ────────────────────────────────────────────────────────
def test_sigma_uses_gravimeter_floor_when_known():
    g = np.array([1.0, 2.0, 3.0])
    sig, method, _ = derive_sigmas_mgal(g, "scintrex_cg6", noise_pct=0.0)
    assert method == "gravimeter_floor:scintrex_cg6"
    assert all(abs(s - 0.005) < 1e-12 for s in sig)  # piso del CG-6


def test_sigma_adaptive_for_unknown_gravimeter():
    g = np.array([10.0])
    sig, method, _ = derive_sigmas_mgal(g, "unknown", noise_pct=0.05)
    assert method == "adaptive_floor"
    assert abs(sig[0] - 0.5) < 1e-9  # max(0.02, 0.05*10) = 0.5


# ── 3. IGRF ──────────────────────────────────────────────────────────────────
def test_igrf_accepts_provided_context():
    overrides, step, needs = resolve_igrf(
        {"inclination_deg": 60.0, "declination_deg": 5.0, "field_intensity_nt": 50000.0}
    )
    assert step.status == STATUS_ALREADY_PRESENT
    assert overrides["field_intensity_nt"] == 50000.0
    assert needs == []


def test_igrf_needs_context_without_location_or_date():
    """Defaults del schema + sin ubicación/fecha → needs_context (NADA fabricado)."""
    overrides, step, needs = resolve_igrf(
        {"inclination_deg": -30.0, "declination_deg": 2.0, "field_intensity_nt": 23500.0}
    )
    assert step.status == STATUS_NEEDS_CONTEXT
    assert overrides == {}
    assert "survey_date" in needs and "utm_zone" in needs


def test_igrf_derived_offline_from_location_and_date():
    """Con ubicación (centroide) + fecha → IGRF-14 derivado offline (física real)."""
    import numpy as np

    lats = np.array([64.5, 64.6])
    lons = np.array([-110.9, -110.8])
    overrides, step, needs = resolve_igrf(
        {"survey_date": "2016"}, lats=lats, lons=lons,
    )
    assert step.status == STATUS_DERIVED
    assert step.method.startswith("IGRF-14")
    assert needs == []
    # Zona ártica de DO-27 (~64.5°N): inclinación alta (>80°).
    assert overrides["inclination_deg"] > 80.0
    assert 50000.0 < overrides["field_intensity_nt"] < 65000.0


# ── 4. Coordenadas: reconstrucción UTM→lat/lon ───────────────────────────────
def test_reconstruct_latlon_from_utm_roundtrips():
    """UTM 19S real → lat/lon plausibles para el norte de Chile."""
    ct = SimpleNamespace(
        absolute_origin={"easting": 400000.0, "northing": 7400000.0},
        epsg_code=None, utm_zone=None,
    )
    obs = [SimpleNamespace(x_m=0.0, z_m=0.0), SimpleNamespace(x_m=300.0, z_m=300.0)]
    out = reconstruct_latlon_from_utm(obs, ct, utm_zone="19S")
    assert out is not None and len(out) == 2
    # Norte de Chile: lat ~ -23.5, lon ~ -69
    assert -25.0 < out[0]["lat_deg"] < -22.0
    assert -71.0 < out[0]["lon_deg"] < -67.0


def test_reconstruct_latlon_returns_none_without_zone():
    ct = SimpleNamespace(
        absolute_origin={"easting": 400000.0, "northing": 7400000.0},
        epsg_code=None, utm_zone=None,
    )
    out = reconstruct_latlon_from_utm([SimpleNamespace(x_m=0.0, z_m=0.0)], ct, utm_zone=None)
    assert out is None


def test_valid_latlon_list_rejects_partial():
    raw = [{"lat_deg": -23.0, "lon_deg": -69.0}, {"lat_deg": None, "lon_deg": -69.0}]
    assert valid_latlon_list(raw, 2) is None


# ── 5. Orquestador: gravedad con lat/lon + elevación presentes ───────────────
def test_enrich_gravity_with_coords_and_elev():
    raw = [{"lat_deg": -23.5, "lon_deg": -69.0, "elev_m": 2500.0 + i} for i in range(9)]
    primary = _primary(n=9, gravity_type="g_raw", raw_latlon=raw)
    res = asyncio.run(enrich_package(primary, data_type="gravity", config={"gravimeter_type": "scintrex_cg6"}))

    assert _step(res, "coordinates").status == STATUS_ALREADY_PRESENT
    assert _step(res, "elevation").status == STATUS_ALREADY_PRESENT
    # g_raw + lat + elev → correcciones aplicadas (Bouguer derivado)
    assert _step(res, "gravity_corrections").status == STATUS_DERIVED
    assert res.g_mgal is not None and res.gravity_type_out == "bouguer_anomaly"
    # σ derivado con piso del CG-6
    assert _step(res, "sigma").status == STATUS_DERIVED
    assert res.sigmas is not None
    assert _step(res, "quality").status == STATUS_DERIVED
    assert "elevation_m" in res.columns_added and "sigma_mgal" in res.columns_added


# ── 6. Orquestador: SIN contexto → aviso accionable (no falla) ───────────────
def test_enrich_gravity_without_context_flags_needs():
    primary = _primary(n=6, gravity_type="g_raw", raw_latlon=None)
    res = asyncio.run(enrich_package(primary, data_type="gravity", config={}, enable_dem=False))

    assert _step(res, "coordinates").status == STATUS_NEEDS_CONTEXT
    assert _step(res, "gravity_corrections").status == STATUS_NEEDS_CONTEXT
    assert "utm_zone" in res.needs_context
    # σ adaptivo SÍ se deriva (no requiere coords): usa la gravedad cruda
    assert _step(res, "sigma").status == STATUS_DERIVED
    # No se fabricó elevación ni Bouguer
    assert res.elevations is None and res.g_mgal is None


# ── 7. Orquestador: DEM inyectado (sin red) completa elevación ───────────────
def test_enrich_dem_injection_fills_elevation():
    raw = [{"lat_deg": -23.5 + 0.001 * i, "lon_deg": -69.0 + 0.001 * i, "elev_m": None} for i in range(5)]
    primary = _primary(n=5, gravity_type="bouguer_anomaly", raw_latlon=raw)

    async def fake_dem(south, north, west, east):
        lon_1d = np.linspace(west, east, 6)
        lat_1d = np.linspace(north, south, 6)  # descendente
        elev = np.full((6, 6), 3000.0)
        return lat_1d, lon_1d, elev, 0.001, {"source": "FAKE/DEM"}

    res = asyncio.run(enrich_package(
        primary, data_type="gravity", config={}, dem_fetcher=fake_dem,
    ))
    elev_step = _step(res, "elevation")
    assert elev_step.status == STATUS_DERIVED
    assert elev_step.method == "opentopo_dem_bilinear"
    assert res.elevations is not None
    assert all(abs(e - 3000.0) < 1e-6 for e in res.elevations)


# ── 8. Orquestador: magnético con/sin IGRF ───────────────────────────────────
def test_enrich_magnetic_igrf_provided():
    primary = _primary(n=8, raw_latlon=None)
    cfg = {"inclination_deg": 75.0, "declination_deg": -10.0, "field_intensity_nt": 55000.0}
    res = asyncio.run(enrich_package(primary, data_type="magnetic", config=cfg, enable_dem=False))
    assert _step(res, "igrf").status == STATUS_ALREADY_PRESENT
    assert res.config_overrides["inclination_deg"] == 75.0
    # σ se delega al motor en magnético
    assert _step(res, "sigma").status == STATUS_SKIPPED


def test_enrich_magnetic_igrf_needs_context_without_location_date():
    primary = _primary(n=8, raw_latlon=None)
    res = asyncio.run(enrich_package(primary, data_type="magnetic", config={}, enable_dem=False))
    assert _step(res, "igrf").status == STATUS_NEEDS_CONTEXT
    assert "survey_date" in res.summary()["needs_context"]
    assert res.summary()["nothing_fabricated"] is True


def test_enrich_magnetic_igrf_derived_offline():
    """Magnetometría con lat/lon + fecha → IGRF derivado offline en el orquestador."""
    raw = [{"lat_deg": 64.5, "lon_deg": -110.9, "elev_m": 400.0} for _ in range(6)]
    primary = _primary(n=6, raw_latlon=raw)
    res = asyncio.run(enrich_package(
        primary, data_type="magnetic", config={"survey_date": "2016-07"}, enable_dem=False,
    ))
    step = _step(res, "igrf")
    assert step.status == STATUS_DERIVED
    assert step.method.startswith("IGRF-14")
    assert res.config_overrides["inclination_deg"] > 80.0
    assert res.summary()["nothing_fabricated"] is True


# ── 9. DEM con clave ausente → needs_context (no falla) ──────────────────────
def test_enrich_dem_key_missing_needs_context():
    raw = [{"lat_deg": -23.5, "lon_deg": -69.0, "elev_m": None} for _ in range(4)]
    primary = _primary(n=4, gravity_type="bouguer_anomaly", raw_latlon=raw)

    from services.opentopo_service import OpenTopoKeyMissingError

    async def no_key(south, north, west, east):
        raise OpenTopoKeyMissingError("OPENTOPO_API_KEY no configurado")

    res = asyncio.run(enrich_package(
        primary, data_type="gravity", config={}, dem_fetcher=no_key,
    ))
    assert _step(res, "elevation").status == STATUS_NEEDS_CONTEXT
    assert "opentopo_api_key" in res.needs_context
    assert res.elevations is None  # no se fabrica
