import { api } from "./client";
import type {
  Thesis,
  ThesisFilters,
  ThesisListResponse,
  ThesisStats,
} from "@/types/thesis";

export async function fetchTheses(
  filters: ThesisFilters = {}
): Promise<ThesisListResponse> {
  const { data } = await api.get<ThesisListResponse>("/api/theses", {
    params: filters,
  });
  return data;
}

export async function fetchThesis(id: string): Promise<Thesis> {
  const { data } = await api.get<Thesis>(`/api/theses/${id}`);
  return data;
}

export async function validateThesis(id: string, notes?: string): Promise<Thesis> {
  const { data } = await api.post<Thesis>(`/api/theses/${id}/validate`, {
    notes,
  });
  return data;
}

export async function dismissThesis(id: string, reason?: string): Promise<Thesis> {
  const { data } = await api.post<Thesis>(`/api/theses/${id}/dismiss`, {
    reason,
  });
  return data;
}

export async function fetchThesisStats(): Promise<ThesisStats> {
  const { data } = await api.get<ThesisStats>("/api/theses/stats");
  return data;
}
