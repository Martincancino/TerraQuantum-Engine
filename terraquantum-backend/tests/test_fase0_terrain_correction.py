"""
FASE 0 Tarea 0.4 — Corrección de terreno: renombrar (no es prisma).
FASE 17 (ACAD-0) — y usar la COMPONENTE VERTICAL, no el módulo.

Historia de este fichero, que es la mitad del defecto:

  - Fase 0 renombró ``compute_terrain_correction_prism`` →
    ``..._pointmass`` porque el nombre prometía el prisma exacto de Nagy y la
    implementación era ``G·ρ·A·|Δh|/r²``.
  - Ese renombrado arregló el NOMBRE y dejó viva la FÓRMULA, que estaba mal:
    ``G·ρ·A·|Δh|/r²`` es el MÓDULO de la atracción de una masa puntual, sin
    proyectar sobre la vertical — que es lo único que mide un gravímetro.
  - Y este fichero la congeló. El test ``test_tc_matches_pointmass_formula``
    reescribía a mano la misma expresión de la línea 182 del servicio y
    comparaba con ``rtol=1e-9``. Un test así no puede fallar nunca: verifica
    que Python sabe multiplicar. Con la fórmula equivocada dentro, pasaba.

  - Fase 17 sustituye la fórmula por la componente vertical de la columna y
    sustituye ese test por una REFERENCIA INDEPENDIENTE: el prisma exacto de
    Nagy (1966), ``exploration/gravimetry.py::_nagy_prism_safe``, que vive en
    otro módulo, lo escribió otro trabajo (el motor directo) y no sabe que la
    corrección de terreno existe.

Verifica:
  - alias deprecados apuntan a la misma función;
  - TC >= 0 siempre (ahora ESTRUCTURAL: el numerador es Δh²);
  - TC = 0 exacta en terreno plano;
  - el valor coincide con el PRISMA DE NAGY, celda a celda y sobre un DEM
    entero — es lo que falla con la fórmula vieja, por dos órdenes de magnitud;
  - las LEYES DE ESCALA (TC ∝ Δh², TC ∝ 1/r³ en campo lejano), que discriminan
    la fórmula vieja (∝|Δh|, ∝1/r²) sin necesidad de Nagy;
  - la forma cerrada estable no se desmorona por cancelación con Δh ≪ r.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import numpy as np
import pytest

from exploration.gravimetry import GravimetryForward
from services.gravity_corrections_service import (
    _G_NEWTON,
    compute_terrain_correction_column,
    compute_terrain_correction_pointmass,
    compute_terrain_correction_prism,
)

RHO_GCC = 2.67
_MGAL_PER_SI = 1e5


# ---------------------------------------------------------------------------
# Referencia INDEPENDIENTE: el prisma exacto de Nagy (1966).
# ---------------------------------------------------------------------------
def _nagy_column_mgal(r_m, dh_m, cell_m, rho_gcc=RHO_GCC):
    """|g_z| [mGal] de una columna vertical cell×cell×|Δh| a distancia
    horizontal ``r_m``, con su base a la cota de la estación.

    Convención de ``_nagy_prism_safe`` (verificada en gravimetry.py:709-713,
    733-771 y en su llamador 865-880):
      - los tres primeros argumentos son (centro_celda − sensor);
      - el eje vertical es ``y``, POSITIVO HACIA ABAJO;
      - devuelve m/s² por cada g/cm³ de densidad (el 1000.0 final es t/m³→kg/m³).
    Masa por encima del sensor ⇒ signo negativo; la TC es una magnitud, así que
    se toma el valor absoluto.
    """
    dh = abs(float(dh_m))
    # Base a la cota del sensor ⇒ centroide media altura POR ENCIMA ⇒ y < 0.
    kernel = GravimetryForward._nagy_prism_safe(
        np.array([float(r_m)]),      # dx: separación horizontal
        np.array([-dh / 2.0]),       # dy: profundidad del centroide (negativa = arriba)
        np.array([0.0]),             # dz: el otro eje horizontal
        float(cell_m), dh, float(cell_m),
        _G_NEWTON,
    )
    return abs(float(np.asarray(kernel).ravel()[0]) * rho_gcc * _MGAL_PER_SI)


def _single_cell_tc(r_m, dh_m, cell_m):
    """TC de un DEM con UNA sola celda elevada a distancia ``r_m``."""
    xs = np.array([0.0, float(r_m)])
    zs = np.array([0.0])
    elev = np.array([[0.0, float(dh_m)]])   # (nz=1, nx=2)
    return float(compute_terrain_correction_column(
        np.array([0.0]), np.array([0.0]), np.array([0.0]),
        xs, zs, elev, float(cell_m),
        reduction_density_gcc=RHO_GCC, max_radius_m=22000.0,
    )[0])


def _dem_with_hill():
    cell = 50.0
    xs = np.arange(0.0, 2000.0, cell)
    zs = np.arange(0.0, 2000.0, cell)
    elev = np.zeros((zs.size, xs.size))
    # Colina suave centrada.
    xx, zz = np.meshgrid(xs, zs)
    elev += 80.0 * np.exp(-(((xx - 1000.0) ** 2 + (zz - 1000.0) ** 2) / (2 * 300.0 ** 2)))
    return xs, zs, elev, cell


# ---------------------------------------------------------------------------
# Nombres
# ---------------------------------------------------------------------------

def test_deprecated_aliases_are_same_function():
    """Los dos nombres históricos siguen resolviendo, y al mismo objeto."""
    assert compute_terrain_correction_prism is compute_terrain_correction_column
    assert compute_terrain_correction_pointmass is compute_terrain_correction_column


# ---------------------------------------------------------------------------
# Propiedades
# ---------------------------------------------------------------------------

def test_tc_non_negative_always():
    xs, zs, elev, cell = _dem_with_hill()
    stations_x = np.array([500.0, 1000.0, 1500.0])
    stations_z = np.array([500.0, 1000.0, 1500.0])
    stations_e = np.array([0.0, 80.0, 0.0])
    tc = compute_terrain_correction_column(
        stations_x, stations_z, stations_e, xs, zs, elev, cell,
        reduction_density_gcc=RHO_GCC, max_radius_m=22000.0,
    )
    assert np.all(tc >= 0.0), f"TC negativa: {tc}"
    assert np.all(np.isfinite(tc))


def test_tc_non_negative_is_structural_not_clipped():
    """La no-negatividad ya no depende de un np.maximum(tc, 0).

    Terreno mitad por encima y mitad por debajo de la estación: con el recorte
    quitado, si la fórmula pudiera dar negativo se vería aquí.
    """
    rng = np.random.default_rng(7)
    cell = 100.0
    xs = np.arange(-2000.0, 2000.0, cell)
    zs = np.arange(-2000.0, 2000.0, cell)
    elev = rng.normal(0.0, 300.0, (zs.size, xs.size))
    tc = compute_terrain_correction_column(
        np.array([0.0]), np.array([0.0]), np.array([0.0]),
        xs, zs, elev, cell, reduction_density_gcc=RHO_GCC, max_radius_m=22000.0,
    )
    assert tc[0] > 0.0 and np.isfinite(tc[0])


def test_tc_flat_terrain_is_exactly_zero():
    """Terreno plano a la cota de la estación ⇒ Δh=0 ⇒ TC EXACTAMENTE 0."""
    cell = 100.0
    xs = np.arange(-1000.0, 1000.0, cell)
    zs = np.arange(-1000.0, 1000.0, cell)
    elev = np.full((zs.size, xs.size), 1234.0)
    tc = compute_terrain_correction_column(
        np.array([0.0]), np.array([0.0]), np.array([1234.0]),
        xs, zs, elev, cell, reduction_density_gcc=RHO_GCC, max_radius_m=22000.0,
    )
    assert tc[0] == 0.0


def test_tc_symmetric_in_hill_and_valley():
    """Colina de +Δh y valle de −Δh al mismo r aportan lo mismo."""
    colina = _single_cell_tc(1500.0, +40.0, 50.0)
    valle = _single_cell_tc(1500.0, -40.0, 50.0)
    assert colina == pytest.approx(valle, rel=1e-12)
    assert colina > 0.0


# ---------------------------------------------------------------------------
# EL GATE: contra el prisma de Nagy (referencia independiente)
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("r_m, dh_m", [(1000.0, 30.0), (2000.0, 30.0), (5000.0, 60.0)])
def test_tc_matches_nagy_prism_far_field(r_m, dh_m):
    """Una celda de DEM contra el prisma exacto de Nagy.

    La aproximación de columna colapsa la sección al eje, con error
    ≈0,375·(celda/r)²; a r ≥ 20 celdas eso es < 1e-3. La fórmula VIEJA
    (G·ρ·A·|Δh|/r²) se desvía por 2r/|Δh| — de 66× a 333× en estos casos — así
    que este test la caza por dos órdenes de magnitud, no por decimales.
    """
    cell = 50.0
    assert r_m / cell >= 20.0, "el test exige campo lejano (r >= 20 celdas)"

    obtenido = _single_cell_tc(r_m, dh_m, cell)
    referencia = _nagy_column_mgal(r_m, dh_m, cell)

    np.testing.assert_allclose(obtenido, referencia, rtol=1e-3)

    # Y que quede escrito por cuánto fallaría la fórmula vieja.
    vieja = _G_NEWTON * RHO_GCC * 1000.0 * cell ** 2 * abs(dh_m) / r_m ** 2 * _MGAL_PER_SI
    assert vieja / referencia > 50.0, (
        f"la fórmula vieja debería estar >50x fuera; está {vieja / referencia:.1f}x"
    )


def test_tc_matches_nagy_over_a_whole_dem():
    """Un DEM entero, sumando Nagy celda a celda.

    Aquí SÍ entran las celdas cercanas, donde la columna subestima al prisma
    (0,71–0,99 del valor exacto), así que la tolerancia es del 25 % — laxa a
    propósito. Sigue siendo demoledora para la fórmula vieja, que sobra por
    un orden de magnitud.
    """
    cell = 100.0
    xs = np.arange(-3000.0, 3000.0, cell)
    zs = np.arange(-3000.0, 3000.0, cell)
    xx, zz = np.meshgrid(xs, zs)
    rr = np.sqrt(xx ** 2 + zz ** 2)
    # Relieve real, con celdas cerca y lejos.
    elev = 250.0 * np.exp(-(rr ** 2) / (2 * 800.0 ** 2))

    se = float(elev[zs.size // 2, xs.size // 2])
    tc = compute_terrain_correction_column(
        np.array([0.0]), np.array([0.0]), np.array([se]),
        xs, zs, elev, cell, reduction_density_gcc=RHO_GCC, max_radius_m=22000.0,
    )[0]

    mask = rr > 0.0
    referencia = sum(
        _nagy_column_mgal(float(r), float(d), cell)
        for r, d in zip(rr[mask].ravel(), (elev - se)[mask].ravel())
    )

    np.testing.assert_allclose(tc, referencia, rtol=0.25)
    assert tc < referencia, "la columna debe SUBESTIMAR al prisma, nunca pasarse"


# ---------------------------------------------------------------------------
# Leyes de escala — discriminan la fórmula vieja SIN usar Nagy
# ---------------------------------------------------------------------------

def test_tc_scales_quadratically_with_relief():
    """TC ∝ Δh². La fórmula vieja escalaba ∝ |Δh| (lineal)."""
    cell, r = 50.0, 4000.0
    base = _single_cell_tc(r, 20.0, cell)
    doble = _single_cell_tc(r, 40.0, cell)
    assert doble / base == pytest.approx(4.0, rel=1e-3), (
        f"esperado x4 (cuadratico), obtenido x{doble / base:.3f}"
    )


def test_tc_scales_as_inverse_cube_of_distance():
    """TC ∝ 1/r³ en campo lejano. La fórmula vieja escalaba ∝ 1/r²."""
    cell, dh = 50.0, 20.0
    cerca = _single_cell_tc(2000.0, dh, cell)
    lejos = _single_cell_tc(4000.0, dh, cell)
    assert cerca / lejos == pytest.approx(8.0, rel=1e-3), (
        f"esperado x8 (cubico), obtenido x{cerca / lejos:.3f}"
    )


def test_closed_form_survives_cancellation_at_tiny_relief():
    """Δh ≪ r: la resta ingenua 1/r − 1/√(r²+Δh²) pierde dígitos.

    A r=22 km con Δh=0,1 m el límite analítico G·ρ·A·Δh²/(2r³) es exacto a
    ~1e-12 relativo, así que sirve de referencia para comprobar que la forma
    estable no se desmorona. La resta ingenua yerra ~8e-6 aquí.
    """
    cell, r, dh = 50.0, 22000.0, 0.1
    obtenido = _single_cell_tc(r, dh, cell)
    limite = _G_NEWTON * RHO_GCC * 1000.0 * cell ** 2 * dh ** 2 / (2 * r ** 3) * _MGAL_PER_SI
    np.testing.assert_allclose(obtenido, limite, rtol=1e-9)

    ingenua = (
        _G_NEWTON * RHO_GCC * 1000.0 * cell ** 2
        * (1.0 / r - 1.0 / np.sqrt(r ** 2 + dh ** 2)) * _MGAL_PER_SI
    )
    assert abs(ingenua - limite) / limite > 1e-7, (
        "si la resta ingenua ya no pierde digitos, este test dejo de tener sentido"
    )
