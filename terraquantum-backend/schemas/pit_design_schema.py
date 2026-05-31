from pydantic import BaseModel
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


class SweepRequest(PitRequest):
    price_min: float
    price_max: float
    steps: int
