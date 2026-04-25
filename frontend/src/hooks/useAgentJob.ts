import { useQuery } from "@tanstack/react-query";
import { fetchJob } from "@/api/companies";

export function useAgentJob(jobId: string | undefined) {
  return useQuery({
    queryKey: ["job", jobId],
    queryFn: () => fetchJob(jobId as string),
    enabled: !!jobId,
    refetchInterval: (query) => {
      const data = query.state.data;
      if (!data) return 2_000;
      return data.status === "completed" || data.status === "failed"
        ? false
        : 2_000;
    },
  });
}
