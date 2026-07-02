"""
Schemas para correcciones de gravedad — Fase 1 del Plan Industrial Tier 1.

Cubre: GRS80 normal gravity, Free-Air (FAC), Bouguer (BC), Terrain (TC).
"""
from __future__ import annotations

from typing import List, Literal, Optional

from pydantic import BaseModel, Field


class CorrectionParams(BaseModel):
    reduction_density_gcc: float = Field(
        default=2.67,
        ge=1.5,
        le=4.0,
        description="Densidad de reducción Bouguer [g/cm³]. Estándar: 2.67.",
    )
    dem_type: Literal["COP30", "SRTM30", "SRTM90", "ALOS", "NASADEM"] = "COP30"
    terrain_radius_m: float = Field(
        default=22000.0,
        ge=1000.0,
        le=200000.0,
        description="Radio máximo de integración de TC [m]. Hammer zones A-M = 22 km.",
    )
    apply_lat_correction: bool = True
    apply_fac: bool = True
    apply_bouguer: bool = True
    apply_terrain: bool = False
    polynomial_regional_order: Optional[int] = Field(
        default=None,
        ge=1,
        le=4,
        description="Orden del polinomio de separación regional. None = sin separación.",
    )


class CorrectedStation(BaseModel):
    station_id: str
    lat_deg: float
    lon_deg: float
    elev_m: float
    g_obs_mgal: float
    gamma_mgal: Optional[float] = None
    fac_mgal: Optional[float] = None
    bc_mgal: Optional[float] = None
    tc_mgal: Optional[float] = None
    g_bouguer_mgal: float
    uncertainty_mgal: float
    gravity_type: str


class CorrectionReport(BaseModel):
    n_stations: int
    corrections_applied: List[str]
    reduction_density_gcc: float
    dem_source: Optional[str] = None
    terrain_radius_m: Optional[float] = None
    fac_min_mgal: Optional[float] = None
    fac_max_mgal: Optional[float] = None
    bc_min_mgal: Optional[float] = None
    bc_max_mgal: Optional[float] = None
    tc_min_mgal: Optional[float] = None
    tc_max_mgal: Optional[float] = None
    g_bouguer_min_mgal: Optional[float] = None
    g_bouguer_max_mgal: Optional[float] = None
    warnings: List[str] = Field(default_factory=list)


class ApplyCorrectionsRequest(BaseModel):
    stations: List[dict]
    params: CorrectionParams = Field(default_factory=CorrectionParams)
    gravity_column: str = Field(
        default="g_obs_mgal",
        description="Nombre de la columna de gravedad observada en cada estación.",
    )
    gravity_type_in: Literal[
        "g_raw",
        "free_air_anomaly",
        "bouguer_anomaly",
        "complete_bouguer_anomaly",
    ] = "g_raw"


class ApplyCorrectionsResponse(BaseModel):
    corrected: List[CorrectedStation]
    report: CorrectionReport
    output_gravity_type: Literal[
        "free_air_anomaly",
        "bouguer_anomaly",
        "complete_bouguer_anomaly",
    ]


