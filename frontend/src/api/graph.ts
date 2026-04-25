import { api } from "./client";
import type { GraphResponse } from "@/types/graph";

export async function fetchFullGraph(refresh = false): Promise<GraphResponse> {
  const { data } = await api.get<GraphResponse>("/api/graph", {
    params: refresh ? { refresh: true } : undefined,
  });
  return data;
}

export async function fetchEgoGraph(
  ticker: string,
  radius = 2
): Promise<GraphResponse> {
  const { data } = await api.get<GraphResponse>(`/api/graph/${ticker}`, {
    params: { radius },
  });
  return data;
}
