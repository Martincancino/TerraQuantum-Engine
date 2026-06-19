"""
Tests Fase 19 Tarea 1 — Auto-detección del tipo de CSV.

Verifica detect_csv_data_type sobre los combos soportados:
  gravity / magnetic / joint / borehole / ambiguous / unknown.
"""
import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from services.gravity_import_service import detect_csv_data_type


def test_detect_gravity():
    r = detect_csv_data_type(["station_id", "x_m", "z_m", "g", "unit", "gravity_type"])
    assert r["detected_type"] == "gravity"
    assert r["confidence"] == "high"
    assert r["has_gravity_column"] and not r["has_magnetic_column"]
    assert r["gravity_column"] == "g"
    assert not r["is_joint_candidate"]


def test_detect_gravity_bouguer_alias():
    r = detect_csv_data_type(["lat", "lon", "complete_bouguer_anomaly", "unit"])
    assert r["detected_type"] == "gravity"
    assert r["gravity_column"] == "complete_bouguer_anomaly"


def test_detect_magnetic():
    r = detect_csv_data_type(["station_id", "lat", "lon", "tmi", "unit"])
    assert r["detected_type"] == "magnetic"
    assert r["has_magnetic_column"] and not r["has_gravity_column"]
    assert r["magnetic_column"] == "tmi"


def test_detect_magnetic_nt_alias():
    r = detect_csv_data_type(["x_m", "z_m", "magnetic_nt"])
    assert r["detected_type"] == "magnetic"


def test_detect_joint_co_located():
    headers = ["lat", "lon", "g", "magnetic_nt", "unit"]
    r = detect_csv_data_type(headers)
    assert r["detected_type"] == "joint"
    assert r["is_joint_candidate"]
    assert r["has_gravity_column"] and r["has_magnetic_column"]
    assert r["warning"] and "joint" in r["warning"].lower()


def test_detect_borehole():
    r = detect_csv_data_type(["hole_id", "depth_from", "depth_to", "density", "lithology"])
    assert r["detected_type"] == "borehole"
    assert r["has_borehole_columns"]
    assert not r["has_gravity_column"] and not r["has_magnetic_column"]


def test_detect_borehole_spanish_aliases():
    r = detect_csv_data_type(["sondaje_id", "desde_m", "hasta_m", "density"])
    assert r["detected_type"] == "borehole"


def test_detect_borehole_requires_interval_pair():
    # Solo depth_from sin depth_to y sin hole_id → no es señal de sondaje suficiente.
    r = detect_csv_data_type(["x_m", "z_m", "g", "depth_from"])
    assert not r["has_borehole_columns"]
    assert r["detected_type"] == "gravity"


def test_detect_unknown():
    r = detect_csv_data_type(["col1", "col2", "foo"])
    assert r["detected_type"] == "unknown"
    assert r["confidence"] == "low"
    assert r["warning"]


def test_detect_ambiguous_geophysics_plus_borehole():
    r = detect_csv_data_type(["hole_id", "depth_from", "depth_to", "g"])
    assert r["detected_type"] == "ambiguous"
    assert r["warning"]


def test_detection_handles_whitespace_and_case():
    r = detect_csv_data_type([" Lat ", "LON", " G ", "Unit"])
    assert r["detected_type"] == "gravity"
