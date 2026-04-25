import { Link, useParams } from "react-router-dom";
import { ArrowLeft, AlertTriangle, Target } from "lucide-react";
import CompanyBadge from "@/components/CompanyBadge";
import ConfidenceScore from "@/components/ConfidenceScore";
import EvidenceChain from "@/components/EvidenceChain";
import { useDismissThesis, useThesis, useValidateThesis } from "@/hooks/useTheses";

export default function ThesisDetail() {
  const { id } = useParams<{ id: string }>();
  const { data: thesis, isLoading, error } = useThesis(id);
  const validate = useValidateThesis();
  const dismiss = useDismissThesis();

  if (isLoading) {
    return <div className="text-mosaic-mute">Loading thesis…</div>;
  }
  if (error || !thesis) {
    return (
      <div className="text-mosaic-short">
        Failed to load thesis. <Link to="/" className="underline">Back to dashboard</Link>
      </div>
    );
  }

  return (
    <div className="space-y-6 max-w-4xl">
      <Link to="/" className="text-sm text-mosaic-accent flex items-center gap-1 hover:underline">
        <ArrowLeft size={14} /> Back to dashboard
      </Link>

      <header className="space-y-3">
        <div className="flex items-start justify-between gap-4">
          <h1 className="text-2xl font-semibold tracking-tight">{thesis.title}</h1>
          <ConfidenceScore value={thesis.confidence_score} />
        </div>
        <div className="flex flex-wrap items-center gap-2 text-sm">
          <span className="text-mosaic-mute">Trigger:</span>
          {thesis.trigger_ticker && (
            <CompanyBadge ticker={thesis.trigger_ticker} variant="trigger" />
          )}
          <span className="text-mosaic-mute">→ Affected:</span>
          {thesis.affected_tickers.map((t) => (
            <CompanyBadge key={t} ticker={t} variant="affected" />
          ))}
          <span className="ml-auto text-xs px-2 py-0.5 rounded border border-mosaic-border uppercase tracking-wide">
            {thesis.direction}
          </span>
        </div>
      </header>

      <section className="prose prose-invert max-w-none">
        <h2 className="text-base font-semibold mb-2">Summary</h2>
        <p className="text-slate-200 whitespace-pre-line">{thesis.summary}</p>
      </section>

      <section>
        <h2 className="text-base font-semibold mb-2">Evidence</h2>
        <EvidenceChain steps={thesis.evidence_chain} />
      </section>

      {thesis.competing_thesis && (
        <section>
          <h2 className="text-base font-semibold mb-2 flex items-center gap-1">
            <AlertTriangle size={14} /> Competing thesis
          </h2>
          <p className="text-sm text-slate-300 italic border-l-2 border-mosaic-border pl-3">
            {thesis.competing_thesis}
          </p>
        </section>
      )}

      {thesis.invalidation_criteria.length > 0 && (
        <section>
          <h2 className="text-base font-semibold mb-2 flex items-center gap-1">
            <Target size={14} /> Invalidation criteria
          </h2>
          <ul className="list-disc list-inside text-sm text-slate-200 space-y-1">
            {thesis.invalidation_criteria.map((c, i) => (
              <li key={i}>{c}</li>
            ))}
          </ul>
        </section>
      )}

      {(thesis.catalyst || thesis.time_horizon) && (
        <section className="grid grid-cols-2 gap-4">
          {thesis.catalyst && (
            <div className="border border-mosaic-border rounded-md p-3 bg-mosaic-panel/60">
              <div className="text-xs text-mosaic-mute mb-1">Catalyst</div>
              <div className="text-sm">{thesis.catalyst}</div>
            </div>
          )}
          {thesis.time_horizon && (
            <div className="border border-mosaic-border rounded-md p-3 bg-mosaic-panel/60">
              <div className="text-xs text-mosaic-mute mb-1">Time horizon</div>
              <div className="text-sm">{thesis.time_horizon}</div>
            </div>
          )}
        </section>
      )}

      {thesis.status === "pending" && (
        <div className="flex items-center gap-3">
          <button
            onClick={() => validate.mutate({ id: thesis.id })}
            className="px-4 py-2 rounded-md bg-mosaic-long/20 text-mosaic-long hover:bg-mosaic-long/30"
          >
            Validate
          </button>
          <button
            onClick={() => dismiss.mutate({ id: thesis.id })}
            className="px-4 py-2 rounded-md border border-mosaic-border text-mosaic-mute hover:text-mosaic-short"
          >
            Dismiss
          </button>
        </div>
      )}
    </div>
  );
}
