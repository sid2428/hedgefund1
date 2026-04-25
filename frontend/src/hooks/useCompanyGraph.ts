import { useQuery } from "@tanstack/react-query";
import { fetchEgoGraph, fetchFullGraph } from "@/api/graph";

export function useFullGraph() {
  return useQuery({
    queryKey: ["graph", "full"],
    queryFn: () => fetchFullGraph(),
    staleTime: 60_000,
  });
}

export function useEgoGraph(ticker: string | undefined, radius = 2) {
  return useQuery({
    queryKey: ["graph", "ego", ticker, radius],
    queryFn: () => fetchEgoGraph(ticker as string, radius),
    enabled: !!ticker,
    staleTime: 60_000,
  });
}
