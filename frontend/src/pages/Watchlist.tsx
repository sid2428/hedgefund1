import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Loader2, Play } from "lucide-react";
import {
  fetchCompanies,
  fetchCompanyFilings,
  ingestCompany,
} from "@/api/companies";
import FilingTimeline from "@/components/FilingTimeline";
import { useAgentJob } from "@/hooks/useAgentJob";

export default function Watchlist() {
  const qc = useQueryClient();
  const [activeTicker, setActiveTicker] = useState<string | null>(null);
  const [activeJob, setActiveJob] = useState<string | undefined>(undefined);

  const companies = useQuery({
    queryKey: ["companies"],
    queryFn: () => fetchCompanies(),
  });

  const filings = useQuery({
    queryKey: ["filings", activeTicker],
    queryFn: () => fetchCompanyFilings(activeTicker as string),
    enabled: !!activeTicker,
  });

  const ingest = useMutation({
    mutationFn: (ticker: string) => ingestCompany(ticker),
    onSuccess: (data) => {
      setActiveJob(data.job_id);
      qc.invalidateQueries({ queryKey: ["filings", activeTicker] });
    },
  });

  const job = useAgentJob(activeJob);

  return (
    <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
      <section className="lg:col-span-1 border border-mosaic-border rounded-md bg-mosaic-panel/60">
        <header className="px-4 py-3 border-b border-mosaic-border">
          <h2 className="font-semibold">Universe</h2>
          <p className="text-xs text-mosaic-mute">
            {companies.data?.total ?? 0} tracked companies
          </p>
        </header>
        <ul className="divide-y divide-mosaic-border max-h-[60vh] overflow-y-auto">
          {(companies.data?.companies ?? []).map((c) => (
            <li
              key={c.id}
              onClick={() => setActiveTicker(c.ticker)}
              className={`px-4 py-2 cursor-pointer hover:bg-mosaic-panel ${
                activeTicker === c.ticker ? "bg-mosaic-panel" : ""
              }`}
            >
              <div className="flex items-baseline justify-between">
                <span className="font-mono text-sm">{c.ticker}</span>
                <span className="text-xs text-mosaic-mute">{c.sector}</span>
              </div>
              <div className="text-xs text-slate-300 truncate">{c.name}</div>
            </li>
          ))}
        </ul>
      </section>

      <section className="lg:col-span-2 space-y-4">
        {!activeTicker ? (
          <div className="border border-dashed border-mosaic-border rounded-md p-12 text-center text-mosaic-mute">
            Select a company to see its filings and trigger ingestion.
          </div>
        ) : (
          <>
            <header className="flex items-center justify-between">
              <h2 className="text-lg font-semibold">{activeTicker} filings</h2>
              <button
                onClick={() => ingest.mutate(activeTicker)}
                disabled={ingest.isPending}
                className="flex items-center gap-2 px-3 py-1.5 text-sm rounded-md bg-mosaic-accent/10 border border-mosaic-accent/40 text-mosaic-accent hover:bg-mosaic-accent/20 disabled:opacity-50"
              >
                {ingest.isPending ? <Loader2 className="animate-spin" size={14} /> : <Play size={14} />}
                Ingest filings
              </button>
            </header>

            {activeJob && job.data && (
              <div className="border border-mosaic-border rounded-md p-3 bg-mosaic-panel/60 text-sm">
                <div className="flex items-center justify-between">
                  <span className="font-mono text-xs">job {job.data.id.slice(0, 8)}</span>
                  <span className="text-xs uppercase tracking-wide">{job.data.status}</span>
                </div>
                {job.data.error && (
                  <div className="text-mosaic-short text-xs mt-1">{job.data.error}</div>
                )}
                {job.data.result && (
                  <pre className="text-xs mt-2 overflow-auto">{JSON.stringify(job.data.result, null, 2)}</pre>
                )}
              </div>
            )}

            {filings.isLoading ? (
              <div className="text-mosaic-mute">Loading filings…</div>
            ) : (
              <FilingTimeline filings={filings.data?.filings ?? []} />
            )}
          </>
        )}
      </section>
    </div>
  );
}
