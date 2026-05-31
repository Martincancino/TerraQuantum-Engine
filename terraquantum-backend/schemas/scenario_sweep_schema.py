from schemas.pit_design_schema import PitRequest


class SweepRequest(PitRequest):
    price_min: float
    price_max: float
    steps: int