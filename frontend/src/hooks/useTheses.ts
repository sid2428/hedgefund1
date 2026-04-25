import {
  useMutation,
  useQuery,
  useQueryClient,
} from "@tanstack/react-query";
import {
  dismissThesis,
  fetchTheses,
  fetchThesis,
  fetchThesisStats,
  validateThesis,
} from "@/api/theses";
import type { Thesis, ThesisFilters } from "@/types/thesis";

export function useTheses(filters: ThesisFilters = {}) {
  return useQuery({
    queryKey: ["theses", filters],
    queryFn: () => fetchTheses(filters),
    refetchInterval: 30_000,
  });
}

export function useThesis(id: string | undefined) {
  return useQuery({
    queryKey: ["thesis", id],
    queryFn: () => fetchThesis(id as string),
    enabled: !!id,
  });
}

export function useThesisStats() {
  return useQuery({
    queryKey: ["thesis-stats"],
    queryFn: fetchThesisStats,
    refetchInterval: 30_000,
  });
}

export function useValidateThesis() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({ id, notes }: { id: string; notes?: string }) =>
      validateThesis(id, notes),
    onMutate: async ({ id }) => {
      // Optimistic: mark validated locally so the UI updates immediately.
      await qc.cancelQueries({ queryKey: ["theses"] });
      const previous = qc.getQueryData<Thesis[] | undefined>(["theses"]);
      return { previous };
    },
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["theses"] });
      qc.invalidateQueries({ queryKey: ["thesis-stats"] });
    },
  });
}

export function useDismissThesis() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({ id, reason }: { id: string; reason?: string }) =>
      dismissThesis(id, reason),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["theses"] });
      qc.invalidateQueries({ queryKey: ["thesis-stats"] });
    },
  });
}
