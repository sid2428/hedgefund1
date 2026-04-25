import { useState } from "react";
import clsx from "clsx";
import { ArrowRight, Check, X } from "lucide-react";
import { Link } from "react-router-dom";
import CompanyBadge from "./CompanyBadge";
import ConfidenceScore from "./ConfidenceScore";
import type { Thesis } from "@/types/thesis";

interface ThesisCardProps {
  thesis: Thesis;
  onValidate: (id: string) => void;
  onDismiss: (id: string) => void;
}

const directionStyles: Record<Thesis["direction"], string> = {
  long: "border-l-mosaic-long",
  short: "border-l-mosaic-short",
  long_short_pair: "border-l-mosaic-pair",
};

const typeLabels: Record<Thesis["thesis_type"], string> = {
  supply_chain_contagion: "Supply chain",
  sector_read_through: "Sector",
  strategic_pivot: "Strategy",
  peer_comparison: "Peer",
};

export default function ThesisCard({
  thesis,
  onValidate,
  onDismiss,
}: ThesisCardProps) {
  const [expanded, setExpanded] = useState(false);
  const truncated = thesis.summary.length > 220;
  const summary = expanded
    ? thesis.summary
    : thesis.summary.slice(0, 220) + (truncated ? "…" : "");

  return (
    <div
      className={clsx(
        "border-l-4 border border-mosaic-border bg-mosaic-panel rounded-md p-4 space-y-3",
        directionStyles[thesis.direction]
      )}
    >
      <div className="flex items-start justify-between gap-3">
        <Link
          to={`/theses/${thesis.id}`}
          className="text-base font-semibold leading-snug hover:text-mosaic-accent"
        >
          {thesis.title}
        </Link>
        <div className="flex items-center gap-2 shrink-0">
          <span className="text-xs px-2 py-0.5 rounded border border-mosaic-border text-mosaic-mute">
            {typeLabels[thesis.thesis_type]}
          </span>
          {thesis.time_horizon && (
            <span className="text-xs px-2 py-0.5 rounded border border-mosaic-border text-mosaic-mute">
              {thesis.time_horizon}
            </span>
          )}
        </div>
      </div>

      <div className="flex items-center flex-wrap gap-2 text-sm">
        {thesis.trigger_ticker && (
          <CompanyBadge ticker={thesis.trigger_ticker} variant="trigger" />
        )}
        <ArrowRight size={14} className="text-mosaic-mute" />
        {thesis.affected_tickers.map((t) => (
          <CompanyBadge key={t} ticker={t} variant="affected" />
        ))}
      </div>

      <p className="text-sm text-slate-200 leading-relaxed whitespace-pre-line">
        {summary}{" "}
        {truncated && (
          <button
            onClick={() => setExpanded((e) => !e)}
            className="text-mosaic-accent hover:underline text-xs"
          >
            {expanded ? "Show less" : "Read more"}
          </button>
        )}
      </p>

      <div className="flex items-center justify-between">
        <ConfidenceScore value={thesis.confidence_score} />
        {thesis.status === "pending" ? (
          <div className="flex items-center gap-2">
            <button
              onClick={() => onValidate(thesis.id)}
              className="flex items-center gap-1 px-3 py-1.5 text-sm rounded-md bg-mosaic-long/20 text-mosaic-long hover:bg-mosaic-long/30 transition-colors"
            >
              <Check size={14} /> Validate
            </button>
            <button
              onClick={() => onDismiss(thesis.id)}
              className="flex items-center gap-1 px-3 py-1.5 text-sm rounded-md border border-mosaic-border text-mosaic-mute hover:text-mosaic-short hover:border-mosaic-short/50 transition-colors"
            >
              <X size={14} /> Dismiss
            </button>
          </div>
        ) : (
          <span
            className={clsx(
              "text-xs px-2 py-1 rounded font-medium uppercase tracking-wide",
              thesis.status === "validated" && "bg-mosaic-long/20 text-mosaic-long",
              thesis.status === "dismissed" && "bg-mosaic-short/20 text-mosaic-short",
              thesis.status === "expired" && "bg-mosaic-mute/20 text-mosaic-mute"
            )}
          >
            {thesis.status}
          </span>
        )}
      </div>
    </div>
  );
}
