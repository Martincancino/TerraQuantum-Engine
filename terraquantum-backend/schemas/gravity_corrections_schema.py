"""
Schemas para correcciones de gravedad — Fase 1 del Plan Industrial Tier 1.

Cubre: GRS80 normal gravity, Free-Air (FAC), Bouguer (BC), Terrain (TC).
"""
from __future__ import annotations

from typing import List, Literal, Optional

from pydantic import BaseModel, ConfigDict, Field


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
    # F2B — pre-reducciones de CAMPO (solo g_raw): marea Longman 1959 y
    # deriva por cierres de base. Requieren time_utc por estación; la deriva
    # además base_station_id (el backend sugiere la candidata si falta).
    apply_tide: bool = False
    apply_drift: bool = False
    drift_method: Literal["linear", "piecewise"] = "linear"
    base_station_id: Optional[str] = None
    polynomial_regional_order: Optional[int] = Field(
        default=None,
        ge=1,
        le=4,
        description="Orden del polinomio de separación regional. None = sin separación.",
    )


class CorrectedStation(BaseModel):
    model_config = ConfigDict(json_schema_serialization_defaults_required=True)  # F11: ver CONTRATO_SERIALIZADO (schemas/response_schema.py)
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
    model_config = ConfigDict(json_schema_serialization_defaults_required=True)  # F11: ver CONTRATO_SERIALIZADO (schemas/response_schema.py)
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
    # F2B — reporte de las pre-reducciones de campo (marea/deriva).
    tide_min_mgal: Optional[float] = None
    tide_max_mgal: Optional[float] = None
    drift_rate_mgal_per_day: Optional[float] = None
    drift_closure_mgal: Optional[float] = None
    drift_n_base: Optional[int] = None
    warnings: List[str] = Field(default_factory=list)


# ── F2B — Separación regional-residual (producto de usuario) ────────────────
class RegionalResidualRequest(BaseModel):
    stations: List[dict]
    method: Literal["polynomial", "upward_continuation"] = "polynomial"
    order: int = Field(default=1, ge=1, le=3)
    height_m: float = Field(default=2000.0, gt=0.0, le=100_000.0)
    value_column: str = Field(
        default="g_bouguer_mgal",
        description="Columna del valor a separar (mGal o nT).",
    )
    include_grids: bool = True
    output_format: Literal["json", "csv"] = "json"


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


