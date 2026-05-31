from typing import List, Optional

from pydantic import BaseModel, Field

from schemas.gravity_import_schema import SpatialReadiness


class CrsContract(BaseModel):
    input_crs: Optional[str] = None
    output_crs: str = "EPSG:4326"
    horizontal_datum: Optional[str] = None
    vertical_datum: Optional[str] = None
    utm_zone: Optional[str] = None
    utm_hemisphere: Optional[str] = None
    epsg_code: Optional[int] = None
    crs_source: str = "missing"
    crs_confidence: str = "MISSING"


class ProjectFootprintCorner(BaseModel):
    lat: Optional[float] = None
    lon: Optional[float] = None


class ProjectFootprint(BaseModel):
    crs: str = "EPSG:4326"
    type: str = "missing"  # "bbox" | "polygon" | "local_reference" | "missing"
    sw: ProjectFootprintCorner = Field(default_factory=ProjectFootprintCorner)
    se: ProjectFootprintCorner = Field(default_factory=ProjectFootprintCorner)
    ne: ProjectFootprintCorner = Field(default_factory=ProjectFootprintCorner)
    nw: ProjectFootprintCorner = Field(default_factory=ProjectFootprintCorner)
    center_lat: Optional[float] = None
    center_lon: Optional[float] = None
    extent_x_m: Optional[float] = None
    extent_z_m: Optional[float] = None
    utm_zone: Optional[str] = None
    # "latlon" | "csv_utm" | "local_meters_anchored" | "derived" | "missing"
    source: str = "missing"
    # "HIGH" | "MEDIUM" | "LOW" | "MISSING"
    confidence: str = "MISSING"
    warnings: List[str] = Field(default_factory=list)
    precision_notes: List[str] = Field(default_factory=list)
    # R2 CRS fields
    utm_hemisphere: Optional[str] = None
    epsg_code: Optional[int] = None
    crs_source: str = "missing"
    crs_confidence: str = "MISSING"


class ProjectCreate(BaseModel):
    project_id: str
    latitude: Optional[float] = Field(None, ge=-90.0, le=90.0)
    longitude: Optional[float] = Field(None, ge=-180.0, le=180.0)
    crs: str = "EPSG:4326"


class ProjectUpdate(BaseModel):
    latitude: Optional[float] = Field(None, ge=-90.0, le=90.0)
    longitude: Optional[float] = Field(None, ge=-180.0, le=180.0)
    crs: Optional[str] = None


class ProjectMeta(BaseModel):
    project_id: str
    latitude: Optional[float] = None
    longitude: Optional[float] = None
    crs: str = "EPSG:4326"
    created_at: str
    updated_at: str
    georef_confidence: str = "LOW"
    georef_type: Optional[str] = None
    utm_zone: Optional[str] = None
    footprint: Optional[ProjectFootprint] = None
    # R2 CRS fields
    input_crs: Optional[str] = None
    epsg_code: Optional[int] = None
    crs_source: str = "missing"
    utm_hemisphere: Optional[str] = None
    horizontal_datum: Optional[str] = None
    crs_contract: Optional[CrsContract] = None
    # R3.5 Spatial Readiness (set when spatial readiness is evaluated)
    spatial_readiness: Optional[SpatialReadiness] = None


class GeorefSummary(BaseModel):
    confidence: str = "MISSING"
    type: str = "missing"
    source: str = "missing"
    has_footprint: bool = False
    has_center: bool = False
    utm_zone: Optional[str] = None
    warnings: List[str] = Field(default_factory=list)


class ProjectFootprintResponse(BaseModel):
    project_id: str
    georef_confidence: str = "MISSING"
    georef_type: str = "local_reference"
    footprint: Optional[ProjectFootprint] = None
    coordinate_system_detected: Optional[str] = None
    utm_zone: Optional[str] = None
    warnings: List[str] = Field(default_factory=list)
    source_run_id: Optional[str] = None


class ProjectResponse(BaseModel):
    project_id: str
    latitude: Optional[float] = None
    longitude: Optional[float] = None
    crs: str = "EPSG:4326"
    created_at: Optional[str] = None
    updated_at: Optional[str] = None
    run_count: int = 0
    georef_confidence: str = "LOW"
    footprint: Optional[ProjectFootprint] = None
