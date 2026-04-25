export interface Company {
  id: string;
  ticker: string;
  cik: string;
  name: string;
  sector: string | null;
  industry: string | null;
  market_cap: number | null;
  created_at: string;
  updated_at: string;
}

export interface CompanyListResponse {
  companies: Company[];
  total: number;
}

export interface Filing {
  id: string;
  company_id: string;
  filing_type: string;
  accession_number: string;
  filed_date: string;
  period_of_report: string | null;
  edgar_url: string | null;
  processed: boolean;
  created_at: string;
}

export interface FilingListResponse {
  filings: Filing[];
  total: number;
}

export interface JobStatus {
  id: string;
  job_type: string;
  status: "queued" | "running" | "completed" | "failed";
  payload?: Record<string, unknown> | null;
  result?: Record<string, unknown> | null;
  error?: string | null;
}
