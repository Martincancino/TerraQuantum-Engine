from typing import Optional

from pydantic import BaseModel, Field


class SpectralAoi(BaseModel):
    center_lat: Optional[float] = None
    center_lon: Optional[float] = None
    buffer_km: Optional[float] = None
    extent_x_m: Optional[float] = None
    extent_z_m: Optional[float] = None
    bbox: dict = Field(default_factory=dict)


class SpectralImageSelection(BaseModel):
    collection: str = "COPERNICUS/S2_SR_HARMONIZED"
    date_start: Optional[str] = None
    date_end: Optional[str] = None
    image_count: Optional[int] = None
    cloud_filter: Optional[str] = None
    snow_filter: Optional[str] = None
    scl_classes_kept: list[int] = Field(default_factory=list)


class SpectralQuality(BaseModel):
    valid_pixel_count: Optional[int] = None
    total_pixel_count: Optional[int] = None
    valid_pixel_ratio: Optional[float] = None
    cloud_mask_used: bool = True
    snow_mask_used: bool = True
    scl_mask_used: bool = True
    scale_m: int = 20


class SpectralIndexStats(BaseModel):
    mean: Optional[float] = None
    p90: Optional[float] = None
    std_dev: Optional[float] = None
    valid_pixel_count: Optional[int] = None
    normalized_score: Optional[float] = None
    status: str = "not_evaluated"
    formula: Optional[str] = None
    warning: Optional[str] = None


class SpectralIndices(BaseModel):
    ndvi: SpectralIndexStats
    iron_oxide_proxy: SpectralIndexStats
    clay_proxy: SpectralIndexStats


class SurfaceSupportScore(BaseModel):
    value: Optional[float] = None
    status: str = "not_evaluated"
    explanation: str = (
        "Proxy superficial de favorabilidad exploratoria; no confirma "
        "mineralizacion ni deposito economico."
    )


class SpectralIndicesBlock(BaseModel):
    version: str
    source: str = "sentinel2_l2a_gee"
    status: str
    cache_key: Optional[str] = None
    computed_at: Optional[str] = None
    aoi: SpectralAoi
    image_selection: SpectralImageSelection
    quality: SpectralQuality
    indices: SpectralIndices
    surface_support_score: SurfaceSupportScore
    disclaimers: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)


class SpectralIndicesResponse(BaseModel):
    project_id: str
    spectral_indices: SpectralIndicesBlock
