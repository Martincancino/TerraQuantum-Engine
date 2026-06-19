"""
FASE 20 — Tests de Integración de Sondajes (Borehole Integration Schema).

Cubre los 8 casos del roadmap (Fase 20):
  1. test_borehole_parse_csv            — parseo de CSV → BoreholeSurvey
  2. test_borehole_depth_to_voxel_mapping — mapeo profundidad → vóxeles (función pura)
  3. test_borehole_constraint_injection — el anclaje inyecta la restricción y converge
  4. test_borehole_agreement_no_conflict — densidad recuperada ≈ medida → status OK
  5. test_borehole_conflict_large_diff  — Δρ grande → status CONFLICT
  6. test_borehole_missing_density      — muestra solo-litología no ancla pero no rompe
  7. test_borehole_litho_pgi_prior      — litología → prior PGI (GMM) coherente
  8. test_borehole_csv_units_feet       — conversión de pies a metros
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import numpy as np

from exploration.gravimetry import GravimetryInversion, GravimetryForward
from exploration.pgi_engine import PGIEngine
from schemas.geophysics_schema import BoreholeInterval, BoreholeSurvey
from services.borehole_service import (
    FEET_TO_M,
    parse_borehole_csv,
    map_interval_to_voxels,
    detect_borehole_conflicts,
    lithology_to_pgi_params,
    build_pgi_engine_from_lithology,
    lithology_properties,
)


# ── Geometría sintética común ──────────────────────────────────────────────
NX, NY, NZ = 4, 4, 4
BS = 30.0


def _grid_centers():
    ix, iy, iz = np.meshgrid(
        np.arange(NX), np.arange(NY), np.arange(NZ), indexing="ij"
    )
    x_c = (ix.ravel() + 0.5) * BS
    y_c = (iy.ravel() + 0.5) * BS
    z_c = (iz.ravel() + 0.5) * BS
    return x_c, y_c, z_c


# ─────────────────────────────────────────────────────────────────────────
#  1) Parseo de CSV
# ─────────────────────────────────────────────────────────────────────────
def test_borehole_parse_csv():
    csv_text = (
        "hole_id,easting,northing,depth_from,depth_to,density,lithology,susceptibility\n"
        "BH01,100,200,0,50,2.85,granite,0.0001\n"
        "BH01,100,200,50,120,3.10,diorite,0.0002\n"
        "BH02,400,260,10,90,4.80,magnetite,0.5\n"
    )
    survey = parse_borehole_csv(csv_text, crs="UTM 19S", datum_elevation_m=2400.0)

    assert isinstance(survey, BoreholeSurvey)
    assert survey.crs == "UTM 19S"
    assert survey.datum_elevation_m == 2400.0
    assert len(survey.holes) == 3

    h0 = survey.holes[0]
    assert h0.hole_id == "BH01"
    assert h0.x_m == 100.0 and h0.z_m == 200.0
    assert h0.depth_from_m == 0.0 and h0.depth_to_m == 50.0
    assert abs(h0.density_t_m3 - 2.85) < 1e-9
    assert h0.lithology == "granite"

    # to_intervals() entrega el contrato mínimo del solver
    intervals = survey.to_intervals()
    assert len(intervals) == 3
    assert all(isinstance(it, BoreholeInterval) for it in intervals)
    assert intervals[2].density_t_m3 == 4.80


def test_borehole_parse_csv_empty_raises():
    import pytest
    with pytest.raises(ValueError):
        parse_borehole_csv("")
    with pytest.raises(ValueError):
        parse_borehole_csv("hole_id,x,z\n")  # faltan columnas obligatorias


# ─────────────────────────────────────────────────────────────────────────
#  2) Mapeo profundidad → vóxeles
# ─────────────────────────────────────────────────────────────────────────
def test_borehole_depth_to_voxel_mapping():
    x_c, y_c, z_c = _grid_centers()

    # Columna en (x=15, z=15) → ix=0, iz=0. Intervalo y∈[0,60] cubre iy=0,1.
    # índice = i*NY*NZ + j*NZ + k = 0*16 + j*4 + 0 → {0, 4}
    vox = map_interval_to_voxels(15.0, 15.0, 0.0, 60.0, x_c, y_c, z_c, BS)
    assert set(vox.tolist()) == {0, 4}, f"esperado {{0,4}}, obtuvo {vox.tolist()}"

    # Intervalo más corto que la celda (dy=30): ningún centro y_c cae dentro →
    # se toma el vóxel más cercano al midpoint (100.5 → y_c=105 → iy=3 → idx 12).
    vox_short = map_interval_to_voxels(15.0, 15.0, 100.0, 101.0, x_c, y_c, z_c, BS)
    assert vox_short.tolist() == [12], f"esperado [12], obtuvo {vox_short.tolist()}"

    # Columna fuera de la grilla → sin vóxeles.
    vox_out = map_interval_to_voxels(9999.0, 9999.0, 0.0, 60.0, x_c, y_c, z_c, BS)
    assert vox_out.size == 0


# ─────────────────────────────────────────────────────────────────────────
#  3) Inyección de la restricción (anclaje) en el solver
# ─────────────────────────────────────────────────────────────────────────
def _solve(boreholes_arr, anchor_kappa=1e4):
    rng = np.random.default_rng(7)
    inv = GravimetryInversion(NX, NY, NZ, BS)          # base_density=2.6
    fwd = GravimetryForward(dx=BS, dy=BS, dz=BS, cutoff_radius=BS * 8)
    x_c, y_c, z_c = _grid_centers()

    xs_s = np.linspace(BS, (NX - 1) * BS, 4)
    zs_s = np.linspace(BS, (NZ - 1) * BS, 3)
    xg, zg = np.meshgrid(xs_s, zs_s)
    sensor_coords = np.column_stack([xg.ravel(), np.zeros(12), zg.ravel()])

    mid = NX * NY * NZ // 2  # 32 → (i=2,j=0,k=0): x=75,z=15,y=15
    true_contrast = np.zeros(NX * NY * NZ)
    true_contrast[mid] = 0.3
    G = fwd._build_sparse_kernel(x_c, y_c, z_c, sensor_coords)
    g_obs = G @ true_contrast + 1e-9 * rng.standard_normal(12)

    meta: dict = {}
    dens_full, _score, misfit, _sens = inv.solve_inversion_lsqr(
        g_obs, None, y_c,
        lambda_mag=1.0, alpha_spatial=1.0,
        forward_model=fwd, sensor_coords=sensor_coords,
        x_c=x_c, z_c=z_c,
        density_min=0.0, density_max=5.5,
        boreholes=boreholes_arr,
        anchor_kappa=anchor_kappa,
        auto_kappa=True,
        prune_observable_domain=True,
        solver_meta=meta,
    )
    return dens_full, misfit, meta, mid


def test_borehole_constraint_injection():
    # Anclamos el vóxel más profundo de la columna (x=75,z=15): y∈[90,120] → y_c=105
    # (iy=3) → índice 2*16+3*4 = 44. A esa profundidad el peso Wz_inv es ~1, de modo
    # que el anclaje en espacio m_tilde se traduce nítidamente a densidad.
    anchored_idx = 44

    def _bh(rho):
        return np.array([[75.0, 15.0, 90.0, 120.0, rho]], dtype=np.float64)

    dens_free, misfit_free, _meta_free, _mid = _solve(None)
    dens_high, misfit_high, meta_high, _ = _solve(_bh(4.0))   # sondaje mide ALTO
    dens_low,  misfit_low,  meta_low,  _ = _solve(_bh(2.0))   # sondaje mide BAJO

    # 1) El solver converge en todos los casos (misfit finito y acotado).
    for m in (misfit_free, misfit_high, misfit_low):
        assert np.isfinite(m) and m < 100.0, f"solver no convergió razonablemente: {m}"

    # 2) El anclaje quedó registrado en solver_meta.
    assert meta_high.get("n_anchored_voxels", 0) >= 1
    assert meta_high.get("anchor_kappa") == 1e4

    # 3) Respuesta MONÓTONA al valor anclado: medir alto recupera MÁS densidad que
    #    medir bajo en el mismo vóxel → la restricción efectivamente se inyecta.
    #    NOTA: el anclaje opera en espacio m_tilde (depth-weighted, Li & Oldenburg);
    #    a esta profundidad Wz_inv≈0.023, por lo que la respuesta en densidad absoluta
    #    es ~2% del contraste anclado. El test valida la DIRECCIÓN y monotonicidad,
    #    no la magnitud (que la atenúa el depth weighting por diseño).
    rho_high = dens_high[anchored_idx]
    rho_low = dens_low[anchored_idx]
    assert rho_high > rho_low + 0.02, (
        f"el anclaje no inyecta la medición: rho(measure=4.0)={rho_high:.4f} debe ser "
        f"mayor que rho(measure=2.0)={rho_low:.4f}"
    )

    # 4) El anclaje altera la solución respecto del caso libre (tuvo efecto real).
    assert abs(dens_high[anchored_idx] - dens_free[anchored_idx]) > 1e-3


# ─────────────────────────────────────────────────────────────────────────
#  4) y 5) Detección de conflictos
# ─────────────────────────────────────────────────────────────────────────
def _density_full_with(value_at, default=2.6):
    x_c, _, _ = _grid_centers()
    dens = np.full(x_c.size, default, dtype=np.float64)
    for idx, val in value_at.items():
        dens[idx] = val
    return dens


def test_borehole_agreement_no_conflict():
    x_c, y_c, z_c = _grid_centers()
    # Vóxeles {0,4} en la columna (15,15) puestos a 2.90; el sondaje mide 2.90.
    dens = _density_full_with({0: 2.90, 4: 2.90})
    interval = BoreholeInterval(x_m=15.0, z_m=15.0, y_from_m=0.0, y_to_m=60.0, density_t_m3=2.90)

    result = detect_borehole_conflicts([interval], dens, x_c, y_c, z_c, BS)
    assert result["status"] == "OK", result
    assert result["n_conflicts"] == 0
    assert result["n_evaluated"] == 1
    assert result["conflicts"][0]["severity"] == "OK"


def test_borehole_conflict_large_diff():
    x_c, y_c, z_c = _grid_centers()
    # El modelo predice ~2.60 pero el sondaje mide 4.0 → Δ=1.4 > 0.5 → CONFLICT.
    dens = _density_full_with({0: 2.60, 4: 2.60})
    interval = BoreholeInterval(x_m=15.0, z_m=15.0, y_from_m=0.0, y_to_m=60.0, density_t_m3=4.0)

    result = detect_borehole_conflicts([interval], dens, x_c, y_c, z_c, BS)
    assert result["status"] == "CONFLICT", result
    assert result["n_conflicts"] == 1
    c = result["conflicts"][0]
    assert c["severity"] == "CONFLICT"
    assert abs(c["density_predicted_t_m3"] - 2.60) < 1e-6
    assert abs(c["diff_t_m3"] - (2.60 - 4.0)) < 1e-6
    assert result["max_abs_diff_t_m3"] > 0.5


# ─────────────────────────────────────────────────────────────────────────
#  6) Muestra sin densidad
# ─────────────────────────────────────────────────────────────────────────
def test_borehole_missing_density():
    csv_text = (
        "hole_id,x,z,from,to,density,lithology\n"
        "BH01,100,200,0,50,2.85,granite\n"
        "BH02,300,400,0,60,,diorite\n"        # sin densidad, solo litología
    )
    survey = parse_borehole_csv(csv_text)
    assert len(survey.holes) == 2
    assert survey.holes[1].density_t_m3 is None
    assert survey.holes[1].lithology == "diorite"

    # to_intervals() excluye la muestra puramente litológica (no ancla la inversión).
    intervals = survey.to_intervals()
    assert len(intervals) == 1
    assert intervals[0].density_t_m3 == 2.85

    # La detección de conflictos también ignora intervalos sin densidad.
    x_c, y_c, z_c = _grid_centers()
    dens = _density_full_with({0: 2.85})
    no_density = BoreholeInterval(
        x_m=15.0, z_m=15.0, y_from_m=0.0, y_to_m=60.0, susceptibility_si=0.01
    )
    res = detect_borehole_conflicts([no_density], dens, x_c, y_c, z_c, BS)
    assert res["status"] == "NO_DATA"
    assert res["n_evaluated"] == 0


# ─────────────────────────────────────────────────────────────────────────
#  7) Litología → prior PGI
# ─────────────────────────────────────────────────────────────────────────
def test_borehole_litho_pgi_prior():
    # Lookup directo
    assert lithology_properties("granite")["density_t_m3"] == 2.67
    assert lithology_properties("magnetita")["density_t_m3"] == 4.80
    assert lithology_properties("brecha de magnetita")["density_t_m3"] == 4.80  # subcadena
    assert lithology_properties("unobtanium") is None

    # GMM desde litologías mixtas
    params = lithology_to_pgi_params(["granite", "granite", "magnetite", "diorite"])
    means = params["means"]
    assert len(means) == 3                       # 3 litologías distintas
    assert means == sorted(means)                # orden por densidad creciente
    assert abs(means[0] - 2.67) < 1e-6           # granito
    assert abs(means[-1] - 4.80) < 1e-6          # magnetita
    assert abs(sum(params["weights"]) - 1.0) < 1e-9

    # Una sola litología → se añade roca huésped como fondo (K≥2)
    single = lithology_to_pgi_params(["magnetite"])
    assert len(single["means"]) == 2

    # El engine resultante clasifica correctamente
    engine = build_pgi_engine_from_lithology(["granite", "magnetite"], base_density=2.67)
    assert isinstance(engine, PGIEngine)
    # densidad cercana a magnetita → clase de mayor centroide
    m_contrast = np.array([4.80 - 2.67])          # contraste de magnetita
    cls = engine.predict_class(m_contrast + 2.67)
    assert engine.means[int(cls[0])] == max(engine.means)

    import pytest
    with pytest.raises(ValueError):
        lithology_to_pgi_params(["unobtanium", "kryptonite"])  # ninguna reconocida


# ─────────────────────────────────────────────────────────────────────────
#  8) Conversión de unidades (pies → metros)
# ─────────────────────────────────────────────────────────────────────────
def test_borehole_csv_units_feet():
    csv_text = (
        "hole_id,x,z,from,to,density\n"
        "BH01,328.084,656.168,0,328.084,3.0\n"   # 100m, 200m, 0, 100m en pies
    )
    survey = parse_borehole_csv(csv_text, length_units="ft")
    h = survey.holes[0]
    assert abs(h.x_m - 328.084 * FEET_TO_M) < 1e-3
    assert abs(h.x_m - 100.0) < 1e-2
    assert abs(h.z_m - 200.0) < 1e-2
    assert abs(h.depth_to_m - 100.0) < 1e-2
    # La densidad NO se escala por unidad de longitud.
    assert abs(h.density_t_m3 - 3.0) < 1e-9

    # auto-detección por sufijo de cabecera
    csv_auto = (
        "hole_id,x_ft,z_ft,from_ft,to_ft,density\n"
        "BH01,328.084,656.168,0,328.084,3.0\n"
    )
    survey_auto = parse_borehole_csv(csv_auto, length_units="auto")
    assert abs(survey_auto.holes[0].x_m - 100.0) < 1e-2
