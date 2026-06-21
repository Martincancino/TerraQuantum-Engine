"""Validación del servicio IGRF-14 offline (armónicos esféricos, sin dependencias).

Compara la inclinación/declinación/intensidad contra valores IGRF-14 publicados
(NOAA/BGS) en varios puntos: ecuador magnético, latitudes medias (London, Boulder),
hemisferio sur (Sydney), polo magnético norte (I→90°) y la zona de DO-27 (~64.5°N,
inclinación ≈83°, que reproduce el valor del dato real). Tolerancias razonables:
±0.6° en ángulos, ±300 nT en intensidad — suficientes para un check externo real
y para atrapar cualquier regresión del algoritmo.

GUARDRAIL: estos no son auto-fijados. Son valores de la calculadora IGRF oficial;
si el algoritmo se rompe, los asserts fallan.
"""
import math

import pytest

from services.igrf_service import (
    igrf_field,
    decimal_year,
    _load_table,
    IgrfOutOfRangeError,
    IgrfError,
    MODEL_NAME,
)

# (nombre, lat, lon, alt_m, año, I_ref, D_ref, F_ref) — valores IGRF-14 publicados.
REFERENCE_POINTS = [
    # Ecuador (Golfo de Guinea): inclinación negativa, declinación oeste ~ -5°.
    ("equator", 0.0, 0.0, 0.0, 2020.0, -30.1, -4.7, 31933.0),
    # London ~2020: declinación cruzó el cero (hecho documentado).
    ("london", 51.5, 0.0, 0.0, 2020.0, 66.5, 0.1, 48882.0),
    # Boulder CO (sitio de prueba WMM), 1.6 km de altitud, 2022.5.
    ("boulder", 40.0, -105.3, 1600.0, 2022.5, 66.2, 8.0, 51553.0),
    # Sydney (hemisferio sur): inclinación empinada negativa, declinación este.
    ("sydney", -33.87, 151.21, 0.0, 2025.0, -64.4, 12.8, 56993.0),
    # DO-27 (Lac de Gras, NWT, ~64.5°N): inclinación ártica ≈83° (reproduce el dato real).
    ("do27", 64.5, -110.9, 0.0, 2016.0, 82.5, 15.1, 58765.0),
]


@pytest.mark.parametrize("name,lat,lon,alt,yr,inc_ref,dec_ref,f_ref", REFERENCE_POINTS)
def test_reference_points(name, lat, lon, alt, yr, inc_ref, dec_ref, f_ref):
    r = igrf_field(lat, lon, alt, yr)
    assert abs(r.inclination_deg - inc_ref) < 0.6, f"{name} I={r.inclination_deg}"
    assert abs(r.declination_deg - dec_ref) < 0.6, f"{name} D={r.declination_deg}"
    assert abs(r.total_intensity_nt - f_ref) < 300.0, f"{name} F={r.total_intensity_nt}"


def test_do27_reproduces_high_inclination():
    """La zona de DO-27 (~64.5°N) debe dar inclinación ártica ~83° (dato real = 83.8°)."""
    r = igrf_field(64.5, -110.9, 0.0, 2016.0)
    assert r.inclination_deg > 80.0
    assert 55000.0 < r.total_intensity_nt < 62000.0


def test_north_dip_pole_inclination_near_90():
    """Cerca del polo magnético norte la inclinación tiende a +90° (campo vertical)."""
    r = igrf_field(86.5, 164.0, 0.0, 2020.0)
    assert r.inclination_deg > 89.0


def test_total_intensity_self_consistent():
    """F = sqrt(X²+Y²+Z²) y H = sqrt(X²+Y²) deben ser internamente consistentes."""
    r = igrf_field(-33.5, -70.6, 1000.0, 2025.0)
    f_calc = math.sqrt(r.north_nt**2 + r.east_nt**2 + r.down_nt**2)
    h_calc = math.hypot(r.north_nt, r.east_nt)
    assert abs(f_calc - r.total_intensity_nt) < 1e-6
    assert abs(h_calc - r.horizontal_nt) < 1e-6
    # I = atan2(Z, H), D = atan2(Y, X).
    assert abs(math.degrees(math.atan2(r.down_nt, r.horizontal_nt)) - r.inclination_deg) < 1e-9


def test_secular_variation_extrapolation_beyond_2025():
    """Más allá de 2025 se extrapola con la variación secular; el campo cambia poco/año."""
    a = igrf_field(40.0, -105.3, 0.0, 2025.0)
    b = igrf_field(40.0, -105.3, 0.0, 2028.0)
    # Variación secular real ~100–150 nT/año en Boulder → < ~200 nT/año acota la extrapolación.
    assert abs(b.total_intensity_nt - a.total_intensity_nt) < 200.0 * 3
    assert a != b


def test_field_changes_with_epoch():
    """El campo del mismo punto debe diferir entre épocas (interpolación temporal real)."""
    old = igrf_field(0.0, 0.0, 0.0, 1960.0)
    new = igrf_field(0.0, 0.0, 0.0, 2020.0)
    assert abs(old.total_intensity_nt - new.total_intensity_nt) > 100.0


# ── Parsing de fecha ─────────────────────────────────────────────────────────
def test_decimal_year_formats():
    assert decimal_year(2016) == 2016.0
    assert decimal_year(2016.5) == 2016.5
    assert decimal_year("2016") == 2016.0
    assert abs(decimal_year("2016-07") - (2016 + 181 / 365.0)) < 1e-6
    assert abs(decimal_year("2016-07-01") - (2016 + 181 / 365.0)) < 1e-6


def test_decimal_year_invalid_raises():
    with pytest.raises(ValueError):
        decimal_year("")
    with pytest.raises(ValueError):
        decimal_year("no-es-fecha")


# ── Rangos y errores ─────────────────────────────────────────────────────────
def test_out_of_range_dates():
    with pytest.raises(IgrfOutOfRangeError):
        igrf_field(0.0, 0.0, 0.0, 1899.0)
    with pytest.raises(IgrfOutOfRangeError):
        igrf_field(0.0, 0.0, 0.0, 2031.0)


def test_invalid_latitude_raises():
    with pytest.raises(IgrfError):
        igrf_field(120.0, 0.0, 0.0, 2020.0)


# ── Integridad del archivo de coeficientes bundleado ─────────────────────────
def test_coefficient_table_bundled():
    table = _load_table()
    assert table.nmax == 13
    # IGRF a grado 13 = 13*(13+2) = 195 coeficientes Schmidt.
    assert len(table.order) == 195
    assert table.values.shape == (195, table.epochs.shape[0])
    # Primer coeficiente del archivo = g(1,0); última época = 2025.0.
    assert table.order[0] == ("g", 1, 0)
    assert table.epochs[-1] == 2025.0
    assert MODEL_NAME == "IGRF-14"
