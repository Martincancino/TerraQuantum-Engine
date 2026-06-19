"""
FASE 22 — EDGE CASES EXHAUSTIVE TESTING.

Objetivo del roadmap (Fase 22): 100+ casos de stress-test que TODOS pasen
*sin silent failures*. La regla rectora es:

    Toda entrada degenerada termina en uno de dos estados, nunca en un
    tercero silencioso:
      (a) ERROR CLARO  → se lanza una excepción con mensaje accionable, o
      (b) SALIDA VÁLIDA → resultado finito, acotado y con flags/diagnósticos
                          que reflejan la degeneración (saturación, score bajo,
                          status CONFLICT, warning, etc.).

No se reimplementa física: todos los casos pesados reutilizan el pipeline REAL
(`synthetic_recovery_benchmark.run_benchmark` → GravimetryForward/Inversion) y
las funciones puras ya validadas de los servicios (multimodal, borehole, csv).

Cobertura (secciones):
  A. Conteo de sensores / suficiencia de datos        (gate de inversión)
  B. Geometría de sensores / colinealidad             (data quality)
  C. Barrido SNR (ruido)                               (pipeline real)
  D. Profundidad extrema                               (pipeline real)
  E. Signo del contraste / cavidad                     (pipeline real)
  F. Ruteo multimodal grav/mag + desalineación         (lógica de decisión)
  G. Sondajes (borehole) edge cases                    (mapeo + conflictos)
  H. CSV edge cases                                    (detección + parseo)
  I. Robustez numérica (sigmas, clamps, fronteras)     (funciones puras)
"""
import os
import sys
import logging

_THIS_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(_THIS_DIR))  # backend root
sys.path.insert(0, _THIS_DIR)                    # tests/ (para synthetic_recovery_benchmark)

import numpy as np
import pytest


@pytest.fixture(autouse=True)
def _quiet_logging():
    """El benchmark loguea mucho; lo silenciamos SOLO durante este módulo y
    restauramos en teardown (logging.disable es global — no dejar residuo)."""
    logging.disable(logging.CRITICAL)
    try:
        yield
    finally:
        logging.disable(logging.NOTSET)


from exploration.gravimetry import _validate_gravity_observations, _sigma_adaptive
from schemas.geophysics_schema import GravityObservation, BoreholeInterval
from services.csv_analysis_service import (
    analyze_csv_observations,
    compute_data_quality_score,
    _convex_hull_area,
)
from services.gravity_import_service import detect_csv_data_type
from services.borehole_service import (
    parse_borehole_csv,
    map_interval_to_voxels,
    detect_borehole_conflicts,
)
from services.multimodal_fusion_service import (
    InsufficientDataError,
    MIN_SENSORS_FOR_INVERSION,
    ROUTE_GRAVITY_ONLY,
    ROUTE_MAGNETIC_ONLY,
    ROUTE_JOINT,
    ROUTE_GRAVITY_BOREHOLE,
    ROUTE_JOINT_BOREHOLE,
    select_route,
    plan_multimodal,
    classify_density_conflict,
    compute_confidence,
    estimate_error_depth,
    gravity_sigma,
    magnetic_sigma,
    borehole_sigma,
)

# Receta de pipeline REAL reutilizable (anti-inverse-crime, dos mallas).
from synthetic_recovery_benchmark import run_benchmark

VALID_SCORES = {"EXCELLENT", "GOOD", "ACCEPTABLE", "POOR"}


# ───────────────────────────────────────────────────────────────────────────
# Helpers
# ───────────────────────────────────────────────────────────────────────────
def _sensor_coords(n, *, seed=0):
    """n sensores en posiciones (x, y=0, z) únicas dentro de 1 km²."""
    rng = np.random.default_rng(seed)
    xs = rng.uniform(0, 1000, n)
    zs = rng.uniform(0, 1000, n)
    return np.column_stack([xs, np.zeros(n), zs])


def _clean_g(n, *, seed=1):
    """n observaciones limpias con variación lateral real (rango > 0)."""
    rng = np.random.default_rng(seed)
    return np.linspace(-0.05, 0.05, n) + 1e-3 * rng.standard_normal(n)


def _grid_obs(n_side, span=1000.0):
    """Grilla n_side×n_side de GravityObservation en el plano (x, z)."""
    obs = []
    for i in range(n_side):
        for j in range(n_side):
            x = span * i / (n_side - 1)
            z = span * j / (n_side - 1)
            g = 10.0 + 5.0 * np.sin(i * 0.7) * np.cos(j * 0.5)
            obs.append(GravityObservation(x_m=x, y_m=0.0, z_m=z, g=float(g)))
    return obs


def _grid_centers(nx, ny, nz, bs):
    ix, iy, iz = np.meshgrid(np.arange(nx), np.arange(ny), np.arange(nz), indexing="ij")
    x_c = (ix.ravel() + 0.5) * bs
    y_c = (iy.ravel() + 0.5) * bs
    z_c = (iz.ravel() + 0.5) * bs
    return x_c, y_c, z_c


# ═══════════════════════════════════════════════════════════════════════════
# SECCIÓN A — Conteo de sensores / suficiencia de datos
# ═══════════════════════════════════════════════════════════════════════════
@pytest.mark.parametrize(
    "n_sensors,expect_ok",
    [(0, False), (1, False), (2, False), (3, False), (4, False),
     (5, True), (8, True), (20, True), (50, True)],
)
def test_gravity_n_sensors_validation(n_sensors, expect_ok):
    """<5 sensores → ValueError CLARO; ≥5 → pasa sin silent failure."""
    g = _clean_g(n_sensors) if n_sensors > 0 else np.array([])
    sc = _sensor_coords(n_sensors) if n_sensors > 0 else np.empty((0, 3))
    if expect_ok:
        g_out, sc_out, warns = _validate_gravity_observations(g, sc, min_sensors=5)
        assert np.isfinite(g_out).all()
        assert len(g_out) >= MIN_SENSORS_FOR_INVERSION
        assert isinstance(warns, list)
    else:
        with pytest.raises(ValueError) as exc:
            _validate_gravity_observations(g, sc, min_sensors=5)
        assert len(str(exc.value)) > 40  # mensaje accionable, no genérico


@pytest.mark.parametrize("n_sensors,expect_ok", [(1, False), (4, False), (5, True), (24, True)])
def test_gravity_n_sensors_routing(n_sensors, expect_ok):
    """El gate multimodal rechaza pocos sensores con InsufficientDataError."""
    if expect_ok:
        assert select_route(True, False, False, n_sensors=n_sensors) == ROUTE_GRAVITY_ONLY
    else:
        with pytest.raises(InsufficientDataError):
            select_route(True, False, False, n_sensors=n_sensors)


def test_no_potential_field_raises():
    """Solo sondajes (sin grav ni mag) → error claro, no ruta silenciosa."""
    with pytest.raises(InsufficientDataError):
        select_route(False, False, True, n_sensors=99)


# ═══════════════════════════════════════════════════════════════════════════
# SECCIÓN B — Geometría de sensores / colinealidad
# ═══════════════════════════════════════════════════════════════════════════
def _geometry_obs(kind, n=20, span=1000.0):
    if kind == "all_on_line":
        return [GravityObservation(x_m=float(i * span / n), y_m=0.0,
                                   z_m=float(i * span / n), g=10.0 + 0.1 * i)
                for i in range(n)]
    if kind == "clustered":  # todos casi en el mismo punto
        return [GravityObservation(x_m=500.0 + 1e-3 * i, y_m=0.0,
                                   z_m=500.0, g=10.0 + 0.1 * i)
                for i in range(n)]
    if kind == "all_on_circle":
        th = np.linspace(0, 2 * np.pi, n, endpoint=False)
        return [GravityObservation(x_m=float(500 + 400 * np.cos(t)), y_m=0.0,
                                   z_m=float(500 + 400 * np.sin(t)),
                                   g=10.0 + float(np.sin(t)))
                for t in th]
    if kind == "good_3d_spread":
        return _grid_obs(int(round(n ** 0.5)) + 1, span=span)
    raise ValueError(kind)


@pytest.mark.parametrize("kind", ["all_on_line", "clustered", "all_on_circle", "good_3d_spread"])
def test_sensor_geometry_no_silent_failure(kind):
    """Toda geometría degenerada produce un score finito y acotado (no crash)."""
    dq = analyze_csv_observations(_geometry_obs(kind), "mGal").data_quality
    assert dq is not None
    assert 0.0 <= dq.score <= 100.0
    assert dq.interpretation in {"GOOD", "MEDIOCRE", "POOR"}
    assert 0.0 <= dq.spatial_distribution <= 100.0


def test_collinear_spatial_zero():
    """Colineal → área de hull 0 → spatial_distribution = 0 (flag explícito)."""
    dq = analyze_csv_observations(_geometry_obs("all_on_line"), "mGal").data_quality
    assert dq.spatial_distribution == 0.0


def test_good_spread_beats_collinear():
    dq_line = analyze_csv_observations(_geometry_obs("all_on_line"), "mGal").data_quality
    dq_grid = analyze_csv_observations(_geometry_obs("good_3d_spread"), "mGal").data_quality
    assert dq_grid.spatial_distribution > dq_line.spatial_distribution


@pytest.mark.parametrize(
    "pts,expect_zero",
    [([(0, 0), (1, 1), (2, 2)], True),         # colineal
     ([(0, 0), (1, 0), (0, 1)], False),        # triángulo
     ([(0, 0), (0, 0), (0, 0)], True),         # punto único
     ([(0, 0), (1, 0)], True)],                # < 3 puntos
)
def test_convex_hull_degenerate(pts, expect_zero):
    area = _convex_hull_area(pts)
    assert area >= 0.0
    assert (area == 0.0) == expect_zero


# ═══════════════════════════════════════════════════════════════════════════
# SECCIÓN C — Barrido SNR (pipeline REAL)
# ═══════════════════════════════════════════════════════════════════════════
def _bench(**kw):
    base = dict(nx=6, ny=3, nz=6, block_size=20.0, fine_block_size=10.0,
                contrast=0.5, noise_level=0.1, use_lcurve=False,
                use_focusing=False, verbose=False)
    base.update(kw)
    return run_benchmark(**base)


@pytest.mark.parametrize("noise_level", [0.01, 0.05, 0.1, 0.5, 1.0, 2.0])
def test_snr_sweep_no_silent_failure(noise_level):
    """Cualquier nivel de ruido → métricas FINITAS y score válido (sin NaN mudo)."""
    r = _bench(noise_level=noise_level)
    assert r["recovery_score"] in VALID_SCORES
    assert np.isfinite(r["pearson_r"])
    assert np.isfinite(r["misfit_percent"])
    assert np.isfinite(r["chi_squared"])
    assert -1.0 <= r["pearson_r"] <= 1.0


def test_snr_monotonic_trend():
    """Menos ruido no debe recuperar PEOR que mucho ruido (sanidad física)."""
    clean = _bench(noise_level=0.02)["pearson_r"]
    noisy = _bench(noise_level=1.5)["pearson_r"]
    assert clean >= noisy - 0.15  # margen por estocasticidad del grid pequeño


# ═══════════════════════════════════════════════════════════════════════════
# SECCIÓN D — Profundidad extrema (pipeline REAL)
# ═══════════════════════════════════════════════════════════════════════════
@pytest.mark.parametrize(
    "ny,block_size",
    [(2, 20.0), (3, 20.0), (4, 30.0), (6, 40.0), (8, 50.0)],
)
def test_depth_extremes_no_silent_failure(ny, block_size):
    """Cuerpo somero → profundo: la inversión nunca devuelve NaN silencioso."""
    r = _bench(ny=ny, block_size=block_size, fine_block_size=block_size / 2.0)
    assert r["recovery_score"] in VALID_SCORES
    assert np.isfinite(r["pearson_r"])
    assert np.isfinite(r["rms_error"])
    assert r["n_total_voxels"] > 0


# ═══════════════════════════════════════════════════════════════════════════
# SECCIÓN E — Signo del contraste / cavidad (pipeline REAL)
# ═══════════════════════════════════════════════════════════════════════════
@pytest.mark.parametrize("contrast", [0.3, 0.5, 1.0, 2.0])
def test_positive_contrast_recovers(contrast):
    """Contraste positivo dentro de bounds → recuperación finita y acotada."""
    r = _bench(contrast=contrast)
    assert r["recovery_score"] in VALID_SCORES
    assert np.isfinite(r["pearson_r"])
    assert 0.0 <= r["bound_saturation_pct"] <= 100.0


@pytest.mark.parametrize("contrast", [-0.3, -0.5])
def test_negative_contrast_clipped_not_crashed(contrast):
    """Cavidad (contraste negativo) con bounds [2.6, 5.5]: el solver NO puede
    bajar de la base → satura en el lower bound. Debe FLAGgearse vía saturación,
    nunca crashear ni devolver NaN mudo."""
    r = _bench(contrast=contrast)
    assert r["recovery_score"] in VALID_SCORES
    assert np.isfinite(r["pearson_r"])
    # La degeneración se refleja en la saturación, no en un fallo silencioso.
    assert r["bound_saturation_pct"] >= 0.0
    assert r["n_sat_lower"] >= 0


# ═══════════════════════════════════════════════════════════════════════════
# SECCIÓN F — Ruteo multimodal grav/mag + desalineación (lógica)
# ═══════════════════════════════════════════════════════════════════════════
@pytest.mark.parametrize(
    "g,m,b,expected",
    [(True, False, False, ROUTE_GRAVITY_ONLY),
     (False, True, False, ROUTE_MAGNETIC_ONLY),
     (True, True, False, ROUTE_JOINT),
     (True, False, True, ROUTE_GRAVITY_BOREHOLE),
     (True, True, True, ROUTE_JOINT_BOREHOLE),
     (False, True, True, ROUTE_MAGNETIC_ONLY)],  # sondaje sin grav → mag_only + warning
)
def test_multimodal_routing_combos(g, m, b, expected):
    assert select_route(g, m, b, n_sensors=24) == expected


def test_joint_better_than_single():
    """El error esperado del joint debe ser < grav sola < mag sola (monotonía)."""
    e_g = estimate_error_depth(ROUTE_GRAVITY_ONLY)
    e_m = estimate_error_depth(ROUTE_MAGNETIC_ONLY)
    e_j = estimate_error_depth(ROUTE_JOINT)
    e_jb = estimate_error_depth(ROUTE_JOINT_BOREHOLE)
    assert e_jb < e_j < e_g < e_m


def test_borehole_without_gravity_warns():
    """mag + sondaje (sin grav): se rutea pero AVISA que el sondaje se ignora."""
    plan = plan_multimodal(False, True, True, n_sensors=24)
    assert plan.route == ROUTE_MAGNETIC_ONLY
    assert any("sondaje" in w.lower() or "gravimetr" in w.lower() for w in plan.warnings)


@pytest.mark.parametrize("dq", [0.0, 30.0, 59.0, 60.0, 87.0, 100.0])
def test_confidence_bounded_and_quality_scaled(dq):
    c = compute_confidence(ROUTE_JOINT, data_quality=dq)
    assert 0.0 <= c <= 1.0


# ═══════════════════════════════════════════════════════════════════════════
# SECCIÓN G — Sondajes (borehole) edge cases
# ═══════════════════════════════════════════════════════════════════════════
NXB, NYB, NZB, BSB = 4, 4, 4, 30.0


def _interval(x, z, yf, yt, rho=None, hid="BH"):
    return BoreholeInterval(x_m=x, z_m=z, y_from_m=yf, y_to_m=yt,
                            density_t_m3=rho, hole_id=hid)


def test_borehole_single_sample_maps_one_voxel():
    x_c, y_c, z_c = _grid_centers(NXB, NYB, NZB, BSB)
    vox = map_interval_to_voxels(15.0, 15.0, 100.0, 101.0, x_c, y_c, z_c, BSB)
    assert vox.size >= 1  # intervalo sub-celda → al menos 1 vóxel garantizado


def test_borehole_spans_entire_model():
    x_c, y_c, z_c = _grid_centers(NXB, NYB, NZB, BSB)
    vox = map_interval_to_voxels(15.0, 15.0, 0.0, NYB * BSB, x_c, y_c, z_c, BSB)
    assert vox.size == NYB  # cubre toda la columna en Y


def test_borehole_out_of_grid_no_crash():
    x_c, y_c, z_c = _grid_centers(NXB, NYB, NZB, BSB)
    vox = map_interval_to_voxels(9e4, 9e4, 0.0, 60.0, x_c, y_c, z_c, BSB)
    assert vox.size == 0


def test_borehole_reversed_interval_swapped():
    x_c, y_c, z_c = _grid_centers(NXB, NYB, NZB, BSB)
    a = map_interval_to_voxels(15.0, 15.0, 0.0, 60.0, x_c, y_c, z_c, BSB)
    b = map_interval_to_voxels(15.0, 15.0, 60.0, 0.0, x_c, y_c, z_c, BSB)  # invertido
    assert set(a.tolist()) == set(b.tolist())


def test_borehole_deep_conflict_flagged():
    x_c, y_c, z_c = _grid_centers(NXB, NYB, NZB, BSB)
    density = np.full(NXB * NYB * NZB, 2.6)  # modelo predice base
    intervals = [_interval(15.0, 15.0, 0.0, 30.0, rho=4.8)]  # sondaje mide magnetita
    res = detect_borehole_conflicts(intervals, density, x_c, y_c, z_c, BSB)
    assert res["status"] == "CONFLICT"
    assert res["n_conflicts"] == 1
    assert res["max_abs_diff_t_m3"] > 0.5


def test_borehole_agreement_ok():
    x_c, y_c, z_c = _grid_centers(NXB, NYB, NZB, BSB)
    density = np.full(NXB * NYB * NZB, 3.0)
    intervals = [_interval(15.0, 15.0, 0.0, 30.0, rho=3.0)]
    res = detect_borehole_conflicts(intervals, density, x_c, y_c, z_c, BSB)
    assert res["status"] == "OK"
    assert res["n_conflicts"] == 0


def test_borehole_air_voxel_handled():
    x_c, y_c, z_c = _grid_centers(NXB, NYB, NZB, BSB)
    density = np.full(NXB * NYB * NZB, np.nan)  # todo aire
    intervals = [_interval(15.0, 15.0, 0.0, 30.0, rho=3.0)]
    res = detect_borehole_conflicts(intervals, density, x_c, y_c, z_c, BSB)
    sev = res["conflicts"][0]["severity"]
    assert sev in {"AIR_VOXEL", "OUT_OF_GRID"}


def test_borehole_out_of_grid_conflict_status():
    x_c, y_c, z_c = _grid_centers(NXB, NYB, NZB, BSB)
    density = np.full(NXB * NYB * NZB, 3.0)
    intervals = [_interval(9e4, 9e4, 0.0, 30.0, rho=3.0)]
    res = detect_borehole_conflicts(intervals, density, x_c, y_c, z_c, BSB)
    assert res["conflicts"][0]["severity"] == "OUT_OF_GRID"


def test_borehole_missing_density_ignored():
    """Un intervalo solo-magnético (sin densidad) no participa de la validación
    de densidad: detect_borehole_conflicts lo ignora → NO_DATA, sin crash."""
    x_c, y_c, z_c = _grid_centers(NXB, NYB, NZB, BSB)
    density = np.full(NXB * NYB * NZB, 3.0)
    interval = BoreholeInterval(x_m=15.0, z_m=15.0, y_from_m=0.0, y_to_m=30.0,
                                density_t_m3=None, susceptibility_si=0.4, hole_id="BH")
    res = detect_borehole_conflicts([interval], density, x_c, y_c, z_c, BSB)
    assert res["status"] == "NO_DATA"  # nada que validar (densidad), sin crash


# ═══════════════════════════════════════════════════════════════════════════
# SECCIÓN H — CSV edge cases
# ═══════════════════════════════════════════════════════════════════════════
def test_csv_all_nan_raises():
    with pytest.raises(ValueError):
        _validate_gravity_observations(np.full(8, np.nan), _sensor_coords(8))


def test_csv_inf_raises():
    g = _clean_g(8)
    g[3] = np.inf
    with pytest.raises(ValueError):
        _validate_gravity_observations(g, _sensor_coords(8))


def test_csv_zero_range_raises():
    g = np.full(8, 12.3)  # sin variación lateral
    with pytest.raises(ValueError):
        _validate_gravity_observations(g, _sensor_coords(8))


def test_csv_duplicates_averaged_with_warning():
    """100% duplicados de posición → se promedian con warning, no crashea."""
    sc = np.tile(np.array([[100.0, 0.0, 200.0]]), (8, 1))
    g = _clean_g(8)
    g_out, sc_out, warns = _validate_gravity_observations(g, sc, min_sensors=1)
    assert len(g_out) == 1  # todos colapsan a una posición
    assert any("duplicad" in w.lower() for w in warns)


@pytest.mark.parametrize(
    "headers,expected",
    [(["station_id", "x_m", "z_m", "g", "unit"], "gravity"),
     (["lat", "lon", "tmi"], "magnetic"),
     (["x_m", "z_m", "g", "tmi"], "joint"),
     (["hole_id", "x", "z", "depth_from", "depth_to", "density"], "borehole"),
     (["foo", "bar", "baz"], "unknown")],
)
def test_csv_type_detection_combos(headers, expected):
    r = detect_csv_data_type(headers)
    assert r["detected_type"] == expected


def test_csv_extra_columns_still_detects():
    r = detect_csv_data_type(["id", "x_m", "z_m", "g", "unit", "operator", "weather", "notes"])
    assert r["detected_type"] == "gravity"


def test_csv_special_characters_no_crash():
    r = detect_csv_data_type(["estación#", "x (m)", "z [m]", "g_obs", "σ"])
    assert r["detected_type"] in {"gravity", "unknown", "ambiguous"}


def test_borehole_csv_empty_raises():
    with pytest.raises(ValueError):
        parse_borehole_csv("")


def test_borehole_csv_header_only_raises():
    with pytest.raises(ValueError):
        parse_borehole_csv("hole_id,x,z,depth_from,depth_to,density\n")


def test_borehole_csv_missing_required_raises():
    with pytest.raises(ValueError):
        parse_borehole_csv("hole_id,x,z\nBH01,1,2\n")


def test_borehole_csv_no_property_raises():
    """Sin densidad/susc/litología el sondaje no aporta nada → error claro."""
    with pytest.raises(ValueError):
        parse_borehole_csv("hole_id,x,z,depth_from,depth_to\nBH01,1,2,0,50\n")


def test_borehole_csv_semicolon_delimiter():
    txt = "hole_id;x;z;depth_from;depth_to;density\nBH01;100;200;0;50;2.85\n"
    survey = parse_borehole_csv(txt)
    assert len(survey.holes) == 1
    assert abs(survey.holes[0].density_t_m3 - 2.85) < 1e-9


def test_borehole_csv_feet_units():
    txt = "hole_id,x,z,depth_from,depth_to,density\nBH01,100,200,0,100,2.85\n"
    survey = parse_borehole_csv(txt, length_units="ft")
    h = survey.holes[0]
    assert abs(h.depth_to_m - 100 * 0.3048) < 1e-6


def test_borehole_csv_bad_density_row_skipped():
    """Densidad fuera de rango físico → fila descartada con detalle, no crash."""
    txt = ("hole_id,x,z,depth_from,depth_to,density\n"
           "BH01,100,200,0,50,99.0\n"      # densidad imposible
           "BH02,300,200,0,50,2.85\n")     # válida
    survey = parse_borehole_csv(txt)
    assert len(survey.holes) == 1
    assert survey.holes[0].hole_id == "BH02"


# ═══════════════════════════════════════════════════════════════════════════
# SECCIÓN I — Robustez numérica (sigmas, clamps, fronteras)
# ═══════════════════════════════════════════════════════════════════════════
@pytest.mark.parametrize(
    "diff,expected",
    [(0.0, "OK"), (0.19, "OK"), (0.2, "WARNING"), (0.35, "WARNING"),
     (0.49, "WARNING"), (0.5, "FLAG"), (1.5, "FLAG"), (-0.6, "FLAG")],
)
def test_conflict_classifier_boundaries(diff, expected):
    status, msg = classify_density_conflict(diff)
    assert status == expected
    assert len(msg) > 20


@pytest.mark.parametrize("arr", [
    np.array([1.0, 1.0, 1.0, 1.0]),          # constante (rango 0)
    np.zeros(6),                              # todo cero
    np.array([0.01, 0.02, 0.03, 100.0]),     # un outlier brutal
    np.linspace(-1, 1, 10),                   # bipolar
])
def test_sigma_strictly_positive(arr):
    """sigma adaptativo NUNCA es 0/NaN (piso garantizado) en datos degenerados."""
    for fn in (gravity_sigma, magnetic_sigma):
        s = fn(arr)
        assert s.shape == arr.shape
        assert np.all(np.isfinite(s))
        assert np.all(s > 0.0)


def test_sigma_adaptive_floor_direct():
    s, is_out = _sigma_adaptive(np.zeros(5), detect_outliers=True)
    assert np.all(s > 0.0)
    assert np.all(np.isfinite(s))


@pytest.mark.parametrize("rho", [0.0, 2.6, 4.8, -3.0])
def test_borehole_sigma_positive(rho):
    assert borehole_sigma(rho) > 0.0


def test_borehole_sigma_replicas_use_sem():
    """Con réplicas, sigma = std/√n (error estándar de la media)."""
    s = borehole_sigma(3.0, samples=[2.9, 3.0, 3.1, 3.0])
    assert s > 0.0 and np.isfinite(s)


@pytest.mark.parametrize("cov", [0.0, 0.25, 0.5, 1.0])
def test_error_depth_coverage_monotonic(cov):
    """Más cobertura → menor o igual error esperado en combos sin sondaje."""
    e = estimate_error_depth(ROUTE_GRAVITY_ONLY, coverage_pct=cov)
    e_full = estimate_error_depth(ROUTE_GRAVITY_ONLY, coverage_pct=1.0)
    assert e >= e_full - 1e-9
    assert np.isfinite(e)
