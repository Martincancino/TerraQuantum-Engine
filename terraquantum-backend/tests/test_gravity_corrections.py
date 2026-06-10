"""
Tests analíticos para gravity_corrections_service.py — H-B1.

Verifican las fórmulas contra valores tabulados GRS80 y criterios exactos
del Plan Industrial Tier 1 (sección 1.13):

    1. GRS80: gamma(0°) = 9.7803267715 m/s², gamma(90°) = 9.8321863685 m/s²
    2. FAC: h=1000 m, lat=-22°  →  FAC ≈ 308.7 mGal  (± 0.5 mGal)
    3. BC:  h=1000 m, rho=2.67  →  BC  ≈ 111.9 mGal  (± 0.1 mGal)
    4. TC siempre >= 0
    5. Nettleton: densidad correcta minimiza |r(BA, elev)|
"""
import sys
import os

# Ajustar path para importar desde terraquantum-backend sin instalación
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import numpy as np

from services.gravity_corrections_service import (
    compute_normal_gravity_grs80,
    compute_normal_gravity_mgal,
    compute_free_air_correction,
    compute_bouguer_correction,
    compute_terrain_correction_prism,
    apply_all_corrections,
    nettleton_analysis,
)

# ---------------------------------------------------------------------------
# 1. Gravedad normal GRS80
# ---------------------------------------------------------------------------

def test_grs80_ecuador():
    """gamma(0°) = 9.7803267715 m/s² (tabulado GRS80)."""
    gamma = compute_normal_gravity_grs80(np.array([0.0]))
    assert abs(gamma[0] - 9.7803267715) < 1e-9, f"Expected 9.7803267715, got {gamma[0]}"


def test_grs80_polo():
    """gamma(90°) = 9.8321863685 m/s² (tabulado GRS80)."""
    gamma = compute_normal_gravity_grs80(np.array([90.0]))
    assert abs(gamma[0] - 9.8321863685) < 1e-7, f"Expected 9.8321863685, got {gamma[0]}"


def test_grs80_chile():
    """Para lat=-22° (norte de Chile), gamma debe estar entre los valores del ecuador y del polo."""
    gamma = compute_normal_gravity_grs80(np.array([-22.0]))
    assert 9.7803 < gamma[0] < 9.8322, f"gamma(-22°) fuera de rango: {gamma[0]}"


def test_grs80_vectorized():
    """Vectorización: array de latitudes produce array del mismo tamaño."""
    lats = np.linspace(-90, 90, 181)
    gamma = compute_normal_gravity_grs80(lats)
    assert gamma.shape == (181,)
    assert np.all(gamma > 9.78) and np.all(gamma < 9.84)


# ---------------------------------------------------------------------------
# 2. Corrección Free-Air
# ---------------------------------------------------------------------------

def test_fac_h1000_lat_22():
    """h=1000 m, lat=-22°  →  FAC ≈ 308.7 mGal (±0.5 mGal según criterio 1.13)."""
    fac = compute_free_air_correction(np.array([1000.0]), np.array([-22.0]))
    assert abs(fac[0] - 308.7) < 0.5, f"FAC esperado ~308.7 mGal, obtenido {fac[0]:.4f}"


def test_fac_at_sea_level():
    """h=0 → FAC = 0 mGal."""
    fac = compute_free_air_correction(np.array([0.0]), np.array([-22.0]))
    assert abs(fac[0]) < 1e-9, f"FAC en h=0 debe ser 0, obtenido {fac[0]}"


def test_fac_positive_for_positive_elevation():
    """FAC debe ser positivo para elevaciones positivas."""
    h = np.array([100.0, 500.0, 2000.0, 4000.0])
    lats = np.full(4, -22.0)
    fac = compute_free_air_correction(h, lats)
    assert np.all(fac > 0), f"FAC negativa para elevaciones positivas: {fac}"


def test_fac_rate_near_standard():
    """Tasa FAC debe ser ~0.3086-0.3088 mGal/m."""
    h = np.array([0.0, 1.0])
    lats = np.full(2, -22.0)
    fac = compute_free_air_correction(h, lats)
    rate = fac[1] - fac[0]
    assert 0.3083 < rate < 0.3092, f"Tasa FAC fuera de rango estándar: {rate:.5f} mGal/m"


# ---------------------------------------------------------------------------
# 3. Corrección Bouguer
# ---------------------------------------------------------------------------

def test_bc_h1000_rho267():
    """h=1000 m, rho=2.67 g/cm³ → BC ≈ 111.9 mGal (±0.1 mGal según criterio 1.13)."""
    bc = compute_bouguer_correction(np.array([1000.0]), reduction_density_gcc=2.67)
    expected = 0.04193 * 2.67 * 1000.0  # = 111.954 mGal
    assert abs(bc[0] - expected) < 0.01, f"BC esperado {expected:.3f} mGal, obtenido {bc[0]:.4f}"


def test_bc_coefficient():
    """Coeficiente Bouguer = 0.04193 ± 0.0001 (criterio 1.13 item 3)."""
    bc_per_m_rho1 = compute_bouguer_correction(np.array([1.0]), reduction_density_gcc=1.0)
    assert abs(bc_per_m_rho1[0] - 0.04193) < 0.0001, (
        f"Coeficiente Bouguer incorrecto: {bc_per_m_rho1[0]:.5f} (esperado 0.04193)"
    )


def test_bc_positive_for_positive_elevation():
    """BC debe ser positiva para elevaciones positivas (se suma masa hacia abajo)."""
    h = np.array([100.0, 500.0, 2000.0])
    bc = compute_bouguer_correction(h, 2.67)
    assert np.all(bc > 0)


def test_bc_zero_at_sea_level():
    """BC = 0 en h=0."""
    bc = compute_bouguer_correction(np.array([0.0]), 2.67)
    assert abs(bc[0]) < 1e-12


# ---------------------------------------------------------------------------
# 4. Corrección de Terreno
# ---------------------------------------------------------------------------

def test_tc_non_negative():
    """TC debe ser siempre >= 0 (propiedad matemática — criterio 1.13 item 4)."""
    n = 5
    station_x = np.zeros(n)
    station_z = np.zeros(n)
    station_elev = np.full(n, 3000.0)

    # DEM con variaciones irregulares
    x = np.linspace(-1000, 1000, 10)
    z = np.linspace(-1000, 1000, 10)
    rng = np.random.default_rng(42)
    dem = 3000.0 + rng.normal(0, 200, (10, 10))

    tc = compute_terrain_correction_prism(
        station_x, station_z, station_elev,
        x, z, dem, dem_cell_size_m=200.0,
        reduction_density_gcc=2.67,
        max_radius_m=5000.0,
    )
    assert np.all(tc >= 0.0), f"TC negativa encontrada: {tc[tc < 0]}"


def test_tc_flat_terrain_is_zero():
    """TC = 0 cuando el terreno es completamente plano (misma elevación que las estaciones)."""
    station_x = np.array([0.0])
    station_z = np.array([0.0])
    station_elev = np.array([1000.0])

    x = np.linspace(-500, 500, 10)
    z = np.linspace(-500, 500, 10)
    dem = np.full((10, 10), 1000.0)  # terreno plano en 1000 m

    tc = compute_terrain_correction_prism(
        station_x, station_z, station_elev,
        x, z, dem, dem_cell_size_m=100.0,
        reduction_density_gcc=2.67,
        max_radius_m=5000.0,
    )
    assert tc[0] < 1e-10, f"TC en terreno plano debería ser ~0, obtenido {tc[0]}"


# ---------------------------------------------------------------------------
# 5. apply_all_corrections
# ---------------------------------------------------------------------------

def test_apply_g_raw_without_elevations_raises():
    """g_raw sin elevaciones debe lanzar ValueError."""
    import pytest
    lats = np.array([-22.0, -22.1])
    lons = np.array([-68.0, -68.1])
    elevs = np.array([float("nan"), float("nan")])
    g = np.array([978100.0, 978101.0])

    try:
        apply_all_corrections(lats, lons, elevs, g, "g_raw",
                               apply_lat=True, apply_fac=True, apply_bouguer=True)
        assert False, "Debería haber lanzado ValueError"
    except ValueError as e:
        assert "elevación" in str(e).lower() or "elevacion" in str(e).lower()


def test_apply_already_bouguer_anomaly_no_op():
    """Si el tipo es bouguer_anomaly, no se aplican correcciones (son un no-op)."""
    lats = np.array([-22.0])
    lons = np.array([-68.0])
    elevs = np.array([3000.0])
    g = np.array([10.0])  # ya es BA

    g_out, meta = apply_all_corrections(
        lats, lons, elevs, g,
        gravity_type_in="bouguer_anomaly",
        apply_lat=True, apply_fac=True, apply_bouguer=True,
    )
    assert meta["corrections_applied"] == []
    assert abs(g_out[0] - g[0]) < 1e-12, "No se deben aplicar correcciones a BA"


def test_apply_g_raw_pipeline_coherent():
    """Para datos g_raw, g_reducido = g_obs - gamma + FAC - BC debe ser coherente."""
    lat = np.array([-22.0])
    lon = np.array([-68.0])
    elev = np.array([3000.0])
    g_obs = np.array([978100.0])  # mGal

    g_out, meta = apply_all_corrections(
        lat, lon, elev, g_obs,
        gravity_type_in="g_raw",
        apply_lat=True, apply_fac=True, apply_bouguer=True,
    )

    # Calcular manualmente
    from services.gravity_corrections_service import (
        compute_normal_gravity_mgal,
        compute_free_air_correction,
        compute_bouguer_correction,
    )
    gamma = compute_normal_gravity_mgal(lat)
    fac = compute_free_air_correction(elev, lat)
    bc = compute_bouguer_correction(elev, 2.67)
    expected = g_obs - gamma + fac - bc

    assert abs(g_out[0] - expected[0]) < 1e-6, (
        f"Pipeline incorrecto: g_out={g_out[0]:.4f} esperado={expected[0]:.4f}"
    )
    assert meta["output_gravity_type"] == "bouguer_anomaly"


# ---------------------------------------------------------------------------
# 6. Nettleton
# ---------------------------------------------------------------------------

def test_nettleton_finds_correct_density():
    """
    Datos sintéticos donde la densidad correcta de Bouguer es 2.67 g/cm³.
    El test verifica que nettleton_analysis() converge cerca de 2.67 ± 0.1.
    """
    rng = np.random.default_rng(0)
    n = 50
    lats = np.full(n, -22.0)
    elevs = rng.uniform(2000, 4000, n)

    # Construir BA "verdadera" con rho=2.67 (no debe correlacionar con elevación)
    gamma_true = compute_normal_gravity_mgal(lats)
    fac_true = compute_free_air_correction(elevs, lats)
    bc_true = compute_bouguer_correction(elevs, 2.67)
    ba_true = rng.normal(5.0, 2.0, n)  # señal geológica sin correlación con topografía

    # g_obs que, con rho=2.67, produce ba_true
    g_obs = ba_true + gamma_true - fac_true + bc_true

    result = nettleton_analysis(g_obs, elevs, lats)
    best = result["best_density_gcc"]
    assert abs(best - 2.67) < 0.15, (
        f"Nettleton no converge: best_density={best:.2f} (esperado ~2.67)"
    )


# ---------------------------------------------------------------------------
# Ejecutar directamente
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import traceback

    tests = [
        test_grs80_ecuador,
        test_grs80_polo,
        test_grs80_chile,
        test_grs80_vectorized,
        test_fac_h1000_lat_22,
        test_fac_at_sea_level,
        test_fac_positive_for_positive_elevation,
        test_fac_rate_near_standard,
        test_bc_h1000_rho267,
        test_bc_coefficient,
        test_bc_positive_for_positive_elevation,
        test_bc_zero_at_sea_level,
        test_tc_non_negative,
        test_tc_flat_terrain_is_zero,
        test_apply_g_raw_without_elevations_raises,
        test_apply_already_bouguer_anomaly_no_op,
        test_apply_g_raw_pipeline_coherent,
        test_nettleton_finds_correct_density,
    ]

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

    print(f"\n{'='*50}")
    print(f"H-B1 gravity_corrections_service — {passed} PASS / {failed} FAIL")
    if failed:
        sys.exit(1)
