"""
R2 — Tests de schemas CRS: CrsContract, ProjectFootprint, ProjectMeta,
CoordSystemDetection, CoordinateTransform.
"""
import pytest
from schemas.project_schema import CrsContract, ProjectFootprint, ProjectMeta
from schemas.gravity_import_schema import CoordSystemDetection, CoordinateTransform


# ---------------------------------------------------------------------------
# CrsContract
# ---------------------------------------------------------------------------

def test_crs_contract_defaults():
    c = CrsContract()
    assert c.output_crs == "EPSG:4326"
    assert c.crs_source == "missing"
    assert c.crs_confidence == "MISSING"
    assert c.input_crs is None
    assert c.epsg_code is None
    assert c.utm_zone is None
    assert c.utm_hemisphere is None
    assert c.horizontal_datum is None
    assert c.vertical_datum is None


def test_crs_contract_serializes_to_json():
    c = CrsContract(
        input_crs="EPSG:32719",
        utm_zone="19S",
        utm_hemisphere="S",
        epsg_code=32719,
        crs_source="user_declared",
        crs_confidence="HIGH",
        horizontal_datum="WGS84",
    )
    d = c.model_dump()
    assert d["epsg_code"] == 32719
    assert d["input_crs"] == "EPSG:32719"
    assert d["utm_zone"] == "19S"
    assert d["crs_source"] == "user_declared"


# ---------------------------------------------------------------------------
# ProjectFootprint — R2 CRS fields
# ---------------------------------------------------------------------------

def test_project_footprint_has_r2_crs_fields():
    fp = ProjectFootprint()
    assert hasattr(fp, "utm_hemisphere")
    assert hasattr(fp, "epsg_code")
    assert hasattr(fp, "crs_source")
    assert hasattr(fp, "crs_confidence")


def test_project_footprint_r2_defaults():
    fp = ProjectFootprint()
    assert fp.utm_hemisphere is None
    assert fp.epsg_code is None
    assert fp.crs_source == "missing"
    assert fp.crs_confidence == "MISSING"


def test_project_footprint_accepts_crs_values():
    fp = ProjectFootprint(
        utm_hemisphere="S",
        epsg_code=32719,
        crs_source="user_declared",
        crs_confidence="HIGH",
    )
    assert fp.utm_hemisphere == "S"
    assert fp.epsg_code == 32719
    assert fp.crs_source == "user_declared"
    assert fp.crs_confidence == "HIGH"


def test_project_footprint_r1_fields_preserved():
    fp = ProjectFootprint(
        crs="EPSG:4326",
        confidence="HIGH",
        source="latlon",
        utm_zone="19S",
    )
    assert fp.crs == "EPSG:4326"
    assert fp.confidence == "HIGH"
    assert fp.source == "latlon"
    assert fp.utm_zone == "19S"


# ---------------------------------------------------------------------------
# ProjectMeta — R2 CRS fields
# ---------------------------------------------------------------------------

def test_project_meta_accepts_crs_contract():
    crs_c = CrsContract(
        input_crs="EPSG:32719",
        epsg_code=32719,
        crs_source="user_declared",
        crs_confidence="HIGH",
        utm_zone="19S",
        utm_hemisphere="S",
    )
    meta = ProjectMeta(
        project_id="test",
        created_at="2026-01-01T00:00:00Z",
        updated_at="2026-01-01T00:00:00Z",
        crs_contract=crs_c,
        input_crs="EPSG:32719",
        epsg_code=32719,
        crs_source="user_declared",
        utm_hemisphere="S",
        horizontal_datum="WGS84",
    )
    assert meta.crs_contract is not None
    assert meta.crs_contract.epsg_code == 32719
    assert meta.input_crs == "EPSG:32719"
    assert meta.utm_hemisphere == "S"


def test_project_meta_r2_defaults():
    meta = ProjectMeta(
        project_id="x",
        created_at="2026-01-01T00:00:00Z",
        updated_at="2026-01-01T00:00:00Z",
    )
    assert meta.input_crs is None
    assert meta.epsg_code is None
    assert meta.crs_source == "missing"
    assert meta.utm_hemisphere is None
    assert meta.horizontal_datum is None
    assert meta.crs_contract is None


# ---------------------------------------------------------------------------
# CoordSystemDetection — R2 CRS fields
# ---------------------------------------------------------------------------

def test_coord_system_detection_r2_fields():
    d = CoordSystemDetection(
        detected="utm",
        confidence="high",
        utm_zone="19S",
        utm_hemisphere="S",
        epsg_code=32719,
        crs_source="csv_column",
    )
    assert d.utm_zone == "19S"
    assert d.utm_hemisphere == "S"
    assert d.epsg_code == 32719
    assert d.crs_source == "csv_column"


def test_coord_system_detection_r2_defaults():
    d = CoordSystemDetection()
    assert d.utm_zone is None
    assert d.utm_hemisphere is None
    assert d.epsg_code is None
    assert d.crs_source == "missing"


# ---------------------------------------------------------------------------
# CoordinateTransform — R2 CRS fields
# ---------------------------------------------------------------------------

def test_coordinate_transform_r2_fields():
    ct = CoordinateTransform(
        input_coordinate_system="utm",
        input_confidence="high",
        utm_zone="19S",
        utm_hemisphere="S",
        epsg_code=32719,
        crs_source="user_declared",
    )
    assert ct.utm_zone == "19S"
    assert ct.utm_hemisphere == "S"
    assert ct.epsg_code == 32719
    assert ct.crs_source == "user_declared"


def test_coordinate_transform_r2_defaults():
    ct = CoordinateTransform()
    assert ct.utm_zone is None
    assert ct.utm_hemisphere is None
    assert ct.epsg_code is None
    assert ct.crs_source == "missing"


def test_coordinate_transform_r1_fields_preserved():
    ct = CoordinateTransform(
        input_coordinate_system="latlon",
        input_confidence="high",
        x_extent_m=50_000.0,
        z_extent_m=40_000.0,
        transformed=True,
    )
    assert ct.input_coordinate_system == "latlon"
    assert ct.x_extent_m == 50_000.0
    assert ct.transformed is True
