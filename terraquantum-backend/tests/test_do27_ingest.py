"""
Tests del adaptador de ingestión DO-27 (scripts/validation/ingest_do27.py).

Verifican la LIMPIEZA de los datos sucios documentados del benchmark:
  • magnético: 2 filas de metadatos IGRF + filas NaN se descartan; IGRF correcto.
  • gravimetría: 0 NaN, rango de Bouguer negativo (kimberlita menos densa).
  • ground truth: el pipe cae dentro del survey y cerca del centro del modelo.
  • frame local: transforma UTM↔local de forma invertible.

Se saltan automáticamente si el dataset DO-27 no está presente (NO se commitea data).
"""
from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest

from scripts.validation.ingest_do27 import (
    build_local_frame,
    load_gravity,
    load_ground_truth,
    load_magnetic,
    _DEFAULT_DO27_ROOT,
)

_HAS_DATA = (_DEFAULT_DO27_ROOT / "DO27_Gravity_mGal.csv").exists()
pytestmark = pytest.mark.skipif(
    not _HAS_DATA, reason="Dataset DO-27 no presente (no se commitea data)."
)


def test_gravity_clean_no_nan():
    g = load_gravity()
    assert g.n == 961, f"se esperaban 961 estaciones gravimétricas, hay {g.n}"
    assert np.isfinite(g.bouguer_mgal).all()
    assert np.isfinite(g.easting).all() and np.isfinite(g.northing).all()
    # Anomalía de Bouguer NEGATIVA: kimberlita menos densa que la caja.
    assert g.bouguer_mgal.max() < 0.0


def test_gravity_utm_range():
    g = load_gravity()
    # Zona DO-27 (NWT, Canadá) en UTM: Easting ~557 km, Northing ~7133 km.
    assert 556000 < g.easting.min() < 558000
    assert 7132000 < g.northing.min() < 7135000


def test_magnetic_drops_metadata_and_nan():
    m = load_magnetic()
    # 963 filas - 2 metadatos = 961 estaciones; se descartan >= 2 filas.
    assert m.n == 961, f"se esperaban 961 estaciones magnéticas, hay {m.n}"
    assert m.n_dropped_nan >= 2
    assert np.isfinite(m.tmi_nt).all()
    # Las coordenadas de estación son UTM, NO los valores de metadatos (83.8/25.4).
    assert m.easting.min() > 1000.0
    assert m.northing.min() > 1000.0


def test_magnetic_igrf_extracted():
    m = load_magnetic()
    # IGRF de TKC: I=83.8°, D=25.4°, B0=60308 nT (campo polar canadiense).
    assert m.inclination_deg == pytest.approx(83.8, abs=0.1)
    assert m.declination_deg == pytest.approx(25.4, abs=0.1)
    assert m.field_intensity_nt == pytest.approx(60308.0, rel=0.01)
    # Rangos físicos.
    assert -90 <= m.inclination_deg <= 90
    assert 20000 <= m.field_intensity_nt <= 70000


def test_ground_truth_pipe_inside_survey():
    g = load_gravity()
    gt_g, gt_m, _ = load_ground_truth()
    # El centroide del pipe verdadero cae DENTRO del footprint del survey.
    assert g.easting.min() <= gt_g.centroid_easting <= g.easting.max()
    assert g.northing.min() <= gt_g.centroid_northing <= g.northing.max()
    # Pipe somero: techo a pocas decenas de metros bajo la superficie.
    assert 0 < gt_g.depth_to_top_m < 100
    assert gt_g.n_body_cells > 1000


def test_ground_truth_grav_and_mag_colocated():
    """Los cuerpos gravimétrico y magnético deben estar co-localizados (mismo pipe)."""
    gt_g, gt_m, _ = load_ground_truth()
    dist = np.hypot(
        gt_g.centroid_easting - gt_m.centroid_easting,
        gt_g.centroid_northing - gt_m.centroid_northing,
    )
    # Mismo pipe; las facies magnéticas (HK1) lo desplazan algo, pero < 150 m.
    assert dist < 150.0


def test_local_frame_roundtrip():
    g = load_gravity()
    m = load_magnetic()
    fr = build_local_frame(g, m)
    # UTM → local → UTM debe ser identidad.
    e, n, z = 557300.0, 7133600.0, 420.0
    assert fr.to_easting(fr.east_local(e)) == pytest.approx(e)
    assert fr.to_northing(fr.north_local(n)) == pytest.approx(n)
    assert fr.to_elevation(float(fr.y_depth(z))) == pytest.approx(z)
    # El datum está por encima de todas las elevaciones de sensores.
    assert fr.datum_elev >= g.elevation.max()
    assert fr.datum_elev >= m.elevation.max()


def test_sensors_matrix_shape_and_depth_sign():
    g = load_gravity()
    fr = build_local_frame(g)
    s = fr.sensors(g.easting, g.northing, g.elevation)
    assert s.shape == (g.n, 3)
    # Profundidad (columna y) >= 0: los sensores están en/bajo el datum.
    assert (s[:, 1] >= -1e-9).all()
