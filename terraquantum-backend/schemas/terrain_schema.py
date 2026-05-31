from typing import List, Optional

from pydantic import BaseModel, Field


class BBoxData(BaseModel):
    min_lat: float
    max_lat: float
    min_lon: float
    max_lon: float


class TerrainMetadata(BaseModel):
    # Campos existentes (no eliminar)
    bbox: BBoxData
    resolution_m: float
    source: str
    dem_rows: int
    dem_cols: int
    center_lat: float
    center_lon: float
    extent_x_m: float
    extent_z_m: float

    # Campos nuevos R3-BE-1
    min_elevation_m: Optional[float] = None
    max_elevation_m: Optional[float] = None
    mean_elevation_m: Optional[float] = None
    cell_size_x_m: float = 0.0
    cell_size_z_m: float = 0.0
    footprint_source: Optional[str] = None
    georef_confidence: str = "MISSING"
    terrain_margin_factor: float = 1.5
    warnings: List[str] = Field(default_factory=list)


class TerrainResponse(BaseModel):
    project_id: str
    dem_matrix: list[list[float]]
    texture_url: str
    metadata: TerrainMetadata
