from pydantic import BaseModel, field_validator
from typing import Optional


class PitRequest(BaseModel):
    file: Optional[str] = None
    project_id: Optional[str] = None
    run_id: Optional[str] = None
    price: float
    recovery: float
    mining_cost: float
    processing_cost: float
    pit_angle: float
    bench_height: float
    berm_width: float = 8.0
    haulage_cost_per_m: float = 0.002
    ramp_gradient: float = 0.10
    block_size_x: float = 10.0
    block_size_y: float = 10.0
    block_size_z: float = 10.0
    exclude_inferred: bool = True

    p_cap: float = 80_000_000.0
    discount_rate: float = 0.10
    fleet_size: int = 20

    @field_validator("price", "mining_cost", "processing_cost", "bench_height")
    @classmethod
    def must_be_positive(cls, v, info):
        if v <= 0:
            raise ValueError(f"{info.field_name} debe ser > 0")
        return v

    @field_validator("recovery")
    @classmethod
    def recovery_valid(cls, v):
        if not 0 < v <= 1:
            raise ValueError("recovery debe estar en (0, 1]")
        return v

    @field_validator("pit_angle")
    @classmethod
    def pit_angle_valid(cls, v):
        if not 0 < v < 90:
            raise ValueError("pit_angle debe estar en (0°, 90°)")
        return v

    @field_validator("fleet_size")
    @classmethod
    def fleet_size_valid(cls, v):
        if v < 1:
            raise ValueError("fleet_size debe ser >= 1")
        return v


class SweepRequest(PitRequest):
    price_min: float
    price_max: float
    steps: int

    @field_validator("steps")
    @classmethod
    def steps_valid(cls, v):
        if v < 1:
            raise ValueError("steps debe ser >= 1")
        return v
