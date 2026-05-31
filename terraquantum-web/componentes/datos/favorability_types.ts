export interface FavorabilityFactor {
  id: string;
  label: string;
  weight: number;
  value?: number | null;
  points: number;
  status: string;
  explanation: string;
}

export interface FavorabilityGates {
  quality_gate: {
    label: string;
    multiplier: number;
    source: string;
    cap?: number | null;
  };
  uncertainty_gate: {
    score: number;
    multiplier: number;
    source: string;
  };
}

export interface FavorabilityResult {
  version: string;
  score: number;
  level: string;
  not_mineral_confirmation: boolean;
  disclaimer: string;
  factors: FavorabilityFactor[];
  gates: FavorabilityGates;
  scoring_detail: {
    weighted_evidence_score: number;
    evaluated_weight_sum: number;
    raw_score_before_cap: number;
    final_score: number;
  };
  warnings: string[];
  computed_at: string;
}
