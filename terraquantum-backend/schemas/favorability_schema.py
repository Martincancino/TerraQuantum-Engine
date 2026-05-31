from typing import List, Optional

from pydantic import BaseModel, Field


class FavorabilityFactor(BaseModel):
    id: str
    label: str
    weight: float
    value: Optional[float] = None
    points: float = 0.0
    status: str
    explanation: str


class FavorabilityQualityGate(BaseModel):
    label: str
    multiplier: float
    source: str
    cap: Optional[float] = None


class FavorabilityUncertaintyGate(BaseModel):
    score: float
    multiplier: float
    source: str


class FavorabilityGates(BaseModel):
    quality_gate: FavorabilityQualityGate
    uncertainty_gate: FavorabilityUncertaintyGate


class FavorabilityScoringDetail(BaseModel):
    weighted_evidence_score: float
    evaluated_weight_sum: float
    raw_score_before_cap: float
    final_score: float


class FavorabilityResult(BaseModel):
    version: str = "0.1"
    score: float
    level: str
    not_mineral_confirmation: bool = True
    disclaimer: str
    factors: List[FavorabilityFactor] = Field(default_factory=list)
    gates: FavorabilityGates
    scoring_detail: FavorabilityScoringDetail
    warnings: List[str] = Field(default_factory=list)
    computed_at: str
