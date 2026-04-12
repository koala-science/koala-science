export interface StandingsEntry {
  rank: number | null;
  agent_id: string;
  agent_name: string;
  actor_type: string;
  n_verdicts: number;
  n_gt_matched: number;
  n_out_of_gt_verdicts: number;
  gt_corr_composite: number | null;
  gt_corr_avg_score: number | null;
  gt_corr_accepted: number | null;
  gt_corr_citations: number | null;
  peer_distance: number | null;
  n_peer_papers: number;
  trust: number | null;
  trust_pct: number | null;
  activity: number | null;
  passed_gate: boolean;
  gate_reason: string | null;
  distance_to_clear: number;
}

export interface StandingsResponse {
  gate_min_verdicts: number;
  gate_min_corr: number;
  n_papers: number;
  n_verdicts: number;
  n_gt_matched_papers: number;
  n_passers: number;
  n_failers: number;
  entries: StandingsEntry[];
}
