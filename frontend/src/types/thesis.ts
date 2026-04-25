export interface EvidenceStep {
  step: number;
  description: string;
  source_company: string;
  source_filing: string;
  quote: string;
}

export type ThesisType =
  | "supply_chain_contagion"
  | "sector_read_through"
  | "strategic_pivot"
  | "peer_comparison";

export type ThesisDirection = "long" | "short" | "long_short_pair";

export type ThesisStatus = "pending" | "validated" | "dismissed" | "expired";

export interface Thesis {
  id: string;
  title: string;
  summary: string;
  thesis_type: ThesisType;
  direction: ThesisDirection;
  confidence_score: number;
  trigger_company_id: string;
  affected_company_ids: string[];
  trigger_ticker: string | null;
  affected_tickers: string[];
  evidence_chain: EvidenceStep[];
  competing_thesis: string | null;
  invalidation_criteria: string[];
  catalyst: string | null;
  time_horizon: string | null;
  status: ThesisStatus;
  pm_notes: string | null;
  created_at: string;
  updated_at: string;
}

export interface ThesisListResponse {
  theses: Thesis[];
  total: number;
  limit: number;
  offset: number;
}

export interface ThesisStats {
  total: number;
  pending: number;
  validated: number;
  dismissed: number;
  expired: number;
}

export interface ThesisFilters {
  status?: ThesisStatus;
  direction?: ThesisDirection;
  confidence_min?: number;
  limit?: number;
  offset?: number;
}
