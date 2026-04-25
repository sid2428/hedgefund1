import { Calendar } from "lucide-react";
import type { Filing } from "@/types/company";

export default function FilingTimeline({ filings }: { filings: Filing[] }) {
  if (!filings || filings.length === 0) {
    return <div className="text-xs text-mosaic-mute">No filings yet.</div>;
  }
  return (
    <ol className="space-y-2">
      {filings.map((f) => (
        <li
          key={f.id}
          className="flex items-center justify-between border border-mosaic-border rounded-md px-3 py-2 bg-mosaic-panel/60"
        >
          <div className="flex items-center gap-3">
            <Calendar size={14} className="text-mosaic-mute" />
            <span className="font-mono text-xs">{f.filing_type}</span>
            <span className="text-sm">{f.filed_date}</span>
          </div>
          <div className="flex items-center gap-2 text-xs">
            <span className={f.processed ? "text-mosaic-long" : "text-mosaic-warn"}>
              {f.processed ? "processed" : "pending"}
            </span>
            {f.edgar_url && (
              <a
                href={f.edgar_url}
                target="_blank"
                rel="noreferrer"
                className="text-mosaic-accent hover:underline"
              >
                EDGAR
              </a>
            )}
          </div>
        </li>
      ))}
    </ol>
  );
}
