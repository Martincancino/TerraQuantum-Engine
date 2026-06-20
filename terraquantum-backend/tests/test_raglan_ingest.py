"""
Tests del adaptador de ingestión Raglan (scripts/validation/ingest_raglan.py).

Verifican la limpieza y la extracción del benchmark de DATO REAL:
  • 1638 estaciones limpias, 0 NaN, σ real (Std_nT) en rango físico.
  • IGRF extraído del header de obs.mag (I=83°, D=−32°, B0=60000), NO inventado.
  • coordenadas LOCALES (no UTM); Z drape constante = 40 m.
  • referencia maginv3d: el PICO de susc cae dentro del survey y coincide con la
    anomalía dominante de los datos.

Se saltan automáticamente si el dataset Raglan no está presente (NO se commitea data).
"""
from __future__ import annotations

import numpy as np
import pytest

from scripts.validation.ingest_raglan import (
    _DEFAULT_RAGLAN_ROOT,
    build_raglan_frame,
    load_raglan_magnetic,
    load_raglan_reference,
)

_HAS_DATA = (_DEFAULT_RAGLAN_ROOT / "Raglan_Magnetic_TMI_nT.csv").exists()
pytestmark = pytest.mark.skipif(
    not _HAS_DATA, reason="Dataset Raglan no presente (no se commitea data)."
)


def test_magnetic_clean_count_and_nan():
    s = load_raglan_magnetic()
    assert s.n == 1638, f"se esperaban 1638 estaciones, hay {s.n}"
    assert s.n_dropped_nan == 0
    assert np.isfinite(s.tmi_nt).all()
    assert np.isfinite(s.east).all() and np.isfinite(s.north).all()


def test_sigma_is_real_per_station():
    s = load_raglan_magnetic()
    # σ = Std_nT real, no constante: hay variación estación a estación.
    assert s.sigma_nt.shape == s.tmi_nt.shape
    assert s.sigma_nt.min() > 0
    assert s.sigma_nt.max() > s.sigma_nt.min()        # variación real
    assert 1.0 < np.median(s.sigma_nt) < 50.0


def test_igrf_from_obs_header():
    s = load_raglan_magnetic()
    # Quebec ártico: I=83°, D=−32°, B0=60000 nT (del header de obs.mag).
    assert s.inclination_deg == pytest.approx(83.0, abs=0.1)
    assert s.declination_deg == pytest.approx(-32.0, abs=0.1)
    assert s.field_intensity_nt == pytest.approx(60000.0, rel=0.01)


def test_local_coords_and_drape():
    s = load_raglan_magnetic()
    # Coordenadas LOCALES (no UTM): del orden de cientos a miles, no ~5e5/7e6.
    assert s.east.max() < 10000 and s.north.max() < 50000
    # Z = drape de vuelo constante (≈40 m).
    assert np.allclose(s.elevation, s.elevation[0])
    assert 20 < s.elevation[0] < 100


def test_reference_peak_inside_survey_and_matches_data():
    s = load_raglan_magnetic()
    ref = load_raglan_reference(survey=s)
    # El PICO de susc de la referencia cae dentro del footprint del survey.
    assert s.east.min() <= ref.peak_east <= s.east.max()
    assert s.north.min() <= ref.peak_north <= s.north.max()
    # El pico de referencia coincide con la anomalía dominante de los datos (< 400 m).
    dist = np.hypot(ref.peak_east - ref.data_anomaly_east, ref.peak_north - ref.data_anomaly_north)
    assert dist < 400.0
    assert ref.susc_max > 0.1
    assert ref.peak_depth_m > 0           # profundidad positiva (bajo superficie)


def test_frame_roundtrip():
    s = load_raglan_magnetic()
    fr = build_raglan_frame(s)
    # local↔data invertible; el datum es la superficie (0) → sensores a y<0 (sobre tierra).
    assert fr.to_easting(fr.z_east(3350.0)) == pytest.approx(3350.0)
    assert fr.to_northing(fr.x_north(40250.0)) == pytest.approx(40250.0)
    sensors = fr.sensors(s.east, s.north, s.elevation)
    assert sensors.shape == (s.n, 3)
    assert (sensors[:, 1] < 0).all()      # profundidad de sensor < 0 = sobre la superficie
