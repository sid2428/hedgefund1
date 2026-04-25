import { api } from "./client";
import type {
  Company,
  CompanyListResponse,
  FilingListResponse,
  JobStatus,
} from "@/types/company";

export async function fetchCompanies(sector?: string): Promise<CompanyListResponse> {
  const { data } = await api.get<CompanyListResponse>("/api/companies", {
    params: sector ? { sector } : undefined,
  });
  return data;
}

export async function fetchCompany(ticker: string): Promise<Company> {
  const { data } = await api.get<Company>(`/api/companies/${ticker}`);
  return data;
}

export async function fetchCompanyFilings(
  ticker: string,
  filing_type?: string
): Promise<FilingListResponse> {
  const { data } = await api.get<FilingListResponse>(
    `/api/companies/${ticker}/filings`,
    { params: filing_type ? { filing_type } : undefined }
  );
  return data;
}

export async function ingestCompany(ticker: string): Promise<{ job_id: string; status: string }> {
  const { data } = await api.post(`/api/companies/${ticker}/ingest`);
  return data;
}

export async function fetchJob(jobId: string): Promise<JobStatus> {
  const { data } = await api.get<JobStatus>(`/api/jobs/${jobId}`);
  return data;
}
